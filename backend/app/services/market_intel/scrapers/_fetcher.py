"""Concrete robots-aware, rate-limited HTTP fetcher.

Shared across all bid-network scrapers (NAPC stub paused, ITD active,
future state-DOTs). Implements the ``Fetcher`` ABC from
``scrapers/_base.py``. The Pipeline orchestrator (slice 4) holds a
single ``HttpFetcher`` instance and calls ``.fetch(url)`` for every
URL in its work queue.

Three guarantees:

  * **Robots-aware.** Each host's ``/robots.txt`` is fetched once
    per process and cached. URLs disallowed under
    ``FieldBridge-Research/1.0`` return ``None`` without an HTTP
    request being issued. If robots.txt itself fails to fetch
    (network error, 5xx) we fail-CLOSED — we don't crawl what we
    can't verify.
  * **Rate-limited per host.** Tracks last-fetch timestamp per host;
    sleeps a jittered 3-6 s before each subsequent fetch to the same
    host. Different hosts proceed without inter-host coordination.
  * **Cookie-isolated by domain.** A single ``httpx.AsyncClient``
    cookie jar honors RFC 6265 domain scoping out of the box —
    cookies set by one host are not sent to another. We document
    that here so a future refactor doesn't accidentally break the
    invariant.

Returns ``FetchedDocument`` on 2xx, ``None`` on anything else
(redirects to non-2xx, 4xx/5xx, robots deny, network/SSL/timeout
error). Never raises on caller-controlled inputs — the pipeline's
fail-soft contract requires clean returns.

Lane: this module is the ONLY place in the scraper that issues
outbound HTTP. The capture script (``scripts/capture_itd_fixtures.py``)
predates the Fetcher and uses httpx directly because fixture capture
is a one-time operator job; production scrape paths must go through
``HttpFetcher``.
"""
from __future__ import annotations

import asyncio
import logging
import random
import ssl
import time
import urllib.robotparser
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.market_intel.scrapers._base import (
    FetchedDocument,
    Fetcher,
)

log = logging.getLogger("fieldbridge.market_intel.fetcher")

USER_AGENT = "FieldBridge-Research/1.0 (+https://fieldbridge.io/bot)"
REQUEST_TIMEOUT_S = 30.0

# Per-host pacing. The same numbers used by the slice-1 registry
# probe — ``do not relax these settings without a real reason``
# (docs/market-intel.md risk-flag).
RATE_LIMIT_MIN_S = 3.0
RATE_LIMIT_MAX_S = 6.0


# ---------------------------------------------------------------------------
# Robots cache

class RobotsCache:
    """Per-host ``RobotFileParser`` cache.

    Fetches each host's robots.txt at most once per process. Failures
    are treated as a hard deny (fail-closed) — we don't crawl a host
    we can't verify. The cache stores the deny verdict so we don't
    retry the same broken host repeatedly.
    """

    # Sentinel value for hosts whose robots.txt failed to fetch.
    # ``can_fetch`` against this returns False for every URL.
    _DENY_ALL = object()

    def __init__(self, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._cache: dict[str, urllib.robotparser.RobotFileParser | object] = {}
        self._http_client = http_client

    async def can_fetch(self, url: str, *, user_agent: str = USER_AGENT) -> bool:
        host_key = self._host_key(url)
        if host_key not in self._cache:
            self._cache[host_key] = await self._fetch_robots(host_key)
        rp = self._cache[host_key]
        if rp is self._DENY_ALL:
            return False
        return rp.can_fetch(user_agent, url)  # type: ignore[union-attr]

    @staticmethod
    def _host_key(url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    async def _fetch_robots(self, host_key: str) -> Any:
        """Fetch and parse ``{host_key}/robots.txt``.

        Per RFC 9309:
          * 200 with body → parse the body.
          * 404 → all paths allowed (permissive).
          * 30x → permissive. We deliberately do NOT follow redirects
            on robots.txt fetches. Some hosts (observed: ITD's
            ``apps.itd.idaho.gov``) 302 robots.txt requests to the
            homepage HTML, and feeding HTML to ``RobotFileParser``
            silently parses as "no rules" — ostensibly permissive,
            but only by accident. Treating 30x as 404-equivalent is
            RFC-compliant and avoids accepting an HTML page as policy.
          * 5xx, network/SSL/timeout error → fail-CLOSED (deny-all).
            Better to skip a host than crawl one we can't verify.
        """
        robots_url = f"{host_key}/robots.txt"
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        try:
            if self._http_client is not None:
                resp = await self._http_client.get(
                    robots_url,
                    headers={"User-Agent": USER_AGENT},
                    timeout=REQUEST_TIMEOUT_S,
                    follow_redirects=False,  # see docstring
                )
                if 300 <= resp.status_code < 400 or resp.status_code == 404:
                    # Permissive by RFC 9309.
                    rp.parse([])
                    log.info(
                        "robots: %s -> %d (permissive)",
                        host_key, resp.status_code,
                    )
                    return rp
                if resp.status_code != 200:
                    log.warning(
                        "robots: %s -> %d; failing closed", host_key, resp.status_code,
                    )
                    return self._DENY_ALL
                rp.parse(resp.text.splitlines())
            else:
                # Sync fallback for callers without an httpx client
                # (e.g. the unit-test path injects a hand-built parser).
                rp.read()
            log.info("robots: cached %s", host_key)
            return rp
        except (
            httpx.HTTPError, httpx.TimeoutException, ssl.SSLError, OSError,
        ) as exc:
            log.warning("robots: %s fetch failed: %s; failing closed", host_key, exc)
            return self._DENY_ALL


# ---------------------------------------------------------------------------
# Rate limiter

class RateLimiter:
    """Per-host last-fetch-time tracker.

    ``acquire(host)`` returns immediately on first hit; subsequent
    hits to the same host sleep for a jittered delay (default
    3-6 s) calculated from the elapsed time since the last fetch.
    Different hosts don't block each other.
    """

    def __init__(
        self,
        *,
        min_delay_s: float = RATE_LIMIT_MIN_S,
        max_delay_s: float = RATE_LIMIT_MAX_S,
        # Test seam: the test suite injects a deterministic clock + sleep.
        clock: Any = time.monotonic,
        sleep: Any = asyncio.sleep,
    ) -> None:
        self._min = min_delay_s
        self._max = max_delay_s
        self._clock = clock
        self._sleep = sleep
        self._last_fetch_at: dict[str, float] = {}

    async def acquire(self, host_key: str) -> float:
        """Block until allowed to fetch ``host_key``. Returns the
        seconds slept (0.0 on first hit)."""
        now = self._clock()
        last = self._last_fetch_at.get(host_key)
        if last is None:
            self._last_fetch_at[host_key] = now
            return 0.0

        target_delay = random.uniform(self._min, self._max)
        elapsed = now - last
        wait = max(0.0, target_delay - elapsed)
        if wait > 0.0:
            log.debug("rate-limit: sleeping %.2fs for %s", wait, host_key)
            await self._sleep(wait)
        # Stamp at the time of fetch issue, not at acquire-call time.
        self._last_fetch_at[host_key] = self._clock()
        return wait


# ---------------------------------------------------------------------------
# Fetcher

class HttpFetcher(Fetcher):
    """Concrete ``Fetcher`` implementation. See module docstring."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        robots_cache: RobotsCache | None = None,
        rate_limiter: RateLimiter | None = None,
        user_agent: str = USER_AGENT,
    ) -> None:
        self._user_agent = user_agent
        if client is None:
            client = httpx.AsyncClient(
                headers={"User-Agent": user_agent, "Accept": "*/*"},
                timeout=httpx.Timeout(REQUEST_TIMEOUT_S, connect=REQUEST_TIMEOUT_S),
                follow_redirects=True,
            )
            self._owns_client = True
        else:
            self._owns_client = False
        self._client = client
        self._robots = robots_cache or RobotsCache(http_client=client)
        self._rate_limiter = rate_limiter or RateLimiter()

    async def __aenter__(self) -> "HttpFetcher":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch(self, url: str) -> FetchedDocument | None:
        if not url.startswith(("http://", "https://")):
            log.warning("fetch: %s — non-http(s) scheme rejected", url)
            return None

        if not await self._robots.can_fetch(url, user_agent=self._user_agent):
            log.info("fetch: %s — robots.txt deny", url)
            return None

        host_key = RobotsCache._host_key(url)
        await self._rate_limiter.acquire(host_key)

        try:
            resp = await self._client.get(url)
        except (httpx.TimeoutException, httpx.PoolTimeout) as exc:
            log.warning("fetch: %s timed out: %s", url, exc)
            return None
        except (ssl.SSLError, httpx.ConnectError) as exc:
            log.warning("fetch: %s connect error: %s", url, exc)
            return None
        except httpx.HTTPError as exc:
            log.warning("fetch: %s http error: %s", url, exc)
            return None

        if not (200 <= resp.status_code < 300):
            log.info("fetch: %s -> HTTP %d (non-2xx)", url, resp.status_code)
            return None

        return FetchedDocument(
            url=url,
            final_url=str(resp.url),
            status=resp.status_code,
            content=resp.content,
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            content_type=resp.headers.get("content-type"),
        )
