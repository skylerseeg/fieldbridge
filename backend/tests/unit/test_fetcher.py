"""Tests for ``app.services.market_intel.scrapers._fetcher``.

Uses ``pytest-httpx`` to mock httpx requests — no live network.
Coverage:

  * 2xx success → FetchedDocument with status, content, content_type
  * 3xx redirect chain → FetchedDocument with final_url updated
  * 4xx / 5xx → None
  * Robots.txt disallow → None, no GET ever attempted
  * Robots.txt 404 → permissive (treated as "no robots, anything goes")
  * Robots.txt fetch fails → fail-closed (None, no GET attempted)
  * Robots.txt cached: second fetch on same host doesn't re-fetch robots
  * Rate limit per host: second fetch to same host sleeps; different
    hosts proceed without inter-host wait
  * Cookie jar: cookie set by host A is sent on second fetch to host A,
    NOT sent on fetch to host B (RFC 6265 domain scoping)
  * Connect error / timeout → None
  * Non-http(s) scheme → None, no GET attempted

Patterns:

  * ``HttpFetcher`` injection takes a custom ``httpx.AsyncClient`` so
    pytest-httpx's mock can intercept. We pass the same client into
    ``RobotsCache`` to keep robots fetches under mock too.
  * ``RateLimiter`` accepts ``clock`` + ``sleep`` injection so the
    tests can assert on wait durations without real time passing.
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.services.market_intel.scrapers._base import FetchedDocument
from app.services.market_intel.scrapers._fetcher import (
    HttpFetcher,
    RateLimiter,
    RobotsCache,
    USER_AGENT,
)

PERMISSIVE_ROBOTS = "User-agent: *\nAllow: /\n"
DENY_ALL_ROBOTS = "User-agent: *\nDisallow: /\n"
NAMED_ALLOWLIST_ROBOTS = (
    "User-agent: Googlebot\nAllow: /\n\n"
    "User-agent: *\nDisallow: /\n"
)


# ---------------------------------------------------------------------------
# Fixtures

@pytest.fixture
async def mocked_client(httpx_mock):  # pytest-httpx provides ``httpx_mock``
    """An httpx.AsyncClient whose requests are intercepted by httpx_mock.

    The fetcher accepts an injected client and reuses it for both
    document fetches and robots.txt fetches. That keeps every outbound
    call under the mock's control.
    """
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        follow_redirects=True,
    ) as client:
        yield client


@pytest.fixture
def fake_clock():
    """Deterministic monotonic clock. Increments on each call by the
    amount given to the most recent ``advance(s)``."""
    state = {"now": 0.0}

    def now() -> float:
        return state["now"]

    def advance(s: float) -> None:
        state["now"] += s

    now.advance = advance  # type: ignore[attr-defined]
    return now


@pytest.fixture
def fake_sleep():
    """Async sleep that records calls instead of actually waiting."""
    waits: list[float] = []

    async def sleep(s: float) -> None:
        waits.append(s)

    sleep.waits = waits  # type: ignore[attr-defined]
    return sleep


def make_fetcher(
    client: httpx.AsyncClient,
    *,
    robots_text: str = PERMISSIVE_ROBOTS,
    rate_limiter: RateLimiter | None = None,
    httpx_mock: Any = None,
) -> HttpFetcher:
    """Build a fetcher whose RobotsCache is pre-seeded with ``robots_text``
    so we don't have to register a robots URL match for every host."""
    cache = RobotsCache(http_client=client)
    # Pre-seed the cache for any host we'll touch by patching its
    # internal _fetch_robots to return a permissive parser. This keeps
    # tests focused — robots-specific behavior gets its own tests.
    import urllib.robotparser

    parsed = urllib.robotparser.RobotFileParser()
    parsed.parse(robots_text.splitlines())

    async def _fake_fetch_robots(host_key: str) -> Any:
        return parsed

    cache._fetch_robots = _fake_fetch_robots  # type: ignore[attr-defined]

    return HttpFetcher(
        client=client,
        robots_cache=cache,
        rate_limiter=rate_limiter or RateLimiter(),
    )


# ---------------------------------------------------------------------------
# Happy path: 2xx → FetchedDocument

async def test_fetch_success_returns_document(httpx_mock, mocked_client):
    httpx_mock.add_response(
        method="GET",
        url="https://example.test/page.html",
        status_code=200,
        content=b"<html>hi</html>",
        headers={"Content-Type": "text/html; charset=utf-8"},
    )
    fetcher = make_fetcher(mocked_client)
    doc = await fetcher.fetch("https://example.test/page.html")

    assert isinstance(doc, FetchedDocument)
    assert doc.status == 200
    assert doc.content == b"<html>hi</html>"
    assert doc.url == "https://example.test/page.html"
    assert doc.final_url == "https://example.test/page.html"
    assert doc.content_type == "text/html; charset=utf-8"
    assert doc.fetched_at  # ISO-8601 string


async def test_fetch_pdf_bytes_round_trip(httpx_mock, mocked_client):
    """Binary PDF content survives the fetcher untouched."""
    pdf_magic = b"%PDF-1.7\n%fake-pdf-bytes\n"
    httpx_mock.add_response(
        method="GET",
        url="https://example.test/abst.pdf",
        status_code=200,
        content=pdf_magic,
        headers={"Content-Type": "application/pdf"},
    )
    fetcher = make_fetcher(mocked_client)
    doc = await fetcher.fetch("https://example.test/abst.pdf")
    assert doc is not None
    assert doc.content == pdf_magic
    assert doc.content_type == "application/pdf"


# ---------------------------------------------------------------------------
# Redirects

async def test_fetch_follows_redirects_and_records_final_url(
    httpx_mock, mocked_client,
):
    httpx_mock.add_response(
        method="GET",
        url="https://example.test/old",
        status_code=301,
        headers={"Location": "https://example.test/new"},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://example.test/new",
        status_code=200,
        content=b"final",
    )
    fetcher = make_fetcher(mocked_client)
    doc = await fetcher.fetch("https://example.test/old")
    assert doc is not None
    assert doc.url == "https://example.test/old"
    assert doc.final_url == "https://example.test/new"
    assert doc.status == 200


# ---------------------------------------------------------------------------
# Non-2xx → None

@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 502, 503])
async def test_fetch_non_2xx_returns_none(httpx_mock, mocked_client, status):
    httpx_mock.add_response(
        method="GET",
        url="https://example.test/bad",
        status_code=status,
    )
    fetcher = make_fetcher(mocked_client)
    assert await fetcher.fetch("https://example.test/bad") is None


# ---------------------------------------------------------------------------
# Robots.txt behavior

async def test_robots_disallow_returns_none_without_get(httpx_mock, mocked_client):
    """When robots.txt denies, no GET is issued — the fetcher returns
    None without calling httpx_mock for the actual URL."""
    fetcher = make_fetcher(mocked_client, robots_text=DENY_ALL_ROBOTS)
    result = await fetcher.fetch("https://denied.test/anything")
    assert result is None
    # pytest-httpx fails the test at teardown if any registered response
    # was unused; we registered nothing for /anything, so no orphan
    # check needed. We DO need to verify no GET was issued though —
    # check that requests list is empty.
    requests = httpx_mock.get_requests()
    assert len(requests) == 0, f"unexpected GET issued: {requests}"


async def test_robots_named_allowlist_blocks_our_ua(httpx_mock, mocked_client):
    """A robots.txt with allowlisted bots + ``User-agent: * Disallow: /``
    catch-all blocks FieldBridge-Research (this is the NAPC pattern)."""
    fetcher = make_fetcher(mocked_client, robots_text=NAMED_ALLOWLIST_ROBOTS)
    assert await fetcher.fetch("https://denied.test/page") is None
    assert len(httpx_mock.get_requests()) == 0


async def test_robots_404_treated_as_permissive(httpx_mock, mocked_client):
    """Some hosts have no robots.txt at all. Standard convention:
    treat as fully permissive."""
    httpx_mock.add_response(
        method="GET",
        url="https://no-robots.test/robots.txt",
        status_code=404,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://no-robots.test/page",
        status_code=200,
        content=b"ok",
    )
    # Build a fetcher WITHOUT pre-seeding the cache — exercise the
    # real ``_fetch_robots`` path.
    cache = RobotsCache(http_client=mocked_client)
    fetcher = HttpFetcher(client=mocked_client, robots_cache=cache)
    doc = await fetcher.fetch("https://no-robots.test/page")
    assert doc is not None
    assert doc.content == b"ok"


async def test_robots_30x_treated_as_permissive(httpx_mock, mocked_client):
    """Some hosts (observed: ITD's apps.itd.idaho.gov) 302-redirect
    robots.txt requests to the homepage HTML. Per RFC 9309 we treat
    that as 404-equivalent (permissive) rather than parsing HTML as
    policy — see ``_fetch_robots`` docstring."""
    httpx_mock.add_response(
        method="GET",
        url="https://redirected.test/robots.txt",
        status_code=302,
        headers={"Location": "https://redirected.test/"},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://redirected.test/anything",
        status_code=200,
        content=b"ok",
    )
    cache = RobotsCache(http_client=mocked_client)
    fetcher = HttpFetcher(client=mocked_client, robots_cache=cache)
    doc = await fetcher.fetch("https://redirected.test/anything")
    assert doc is not None
    # Crucial: only the robots.txt request was issued, NOT the redirect
    # target. We didn't follow into the homepage.
    requests = httpx_mock.get_requests()
    paths = [r.url.path for r in requests]
    assert paths.count("/robots.txt") == 1
    assert "/" not in paths  # redirect target NOT fetched


async def test_robots_5xx_fails_closed(httpx_mock, mocked_client):
    """If robots.txt itself 5xxs, we don't crawl. Better safe than sorry."""
    httpx_mock.add_response(
        method="GET",
        url="https://broken.test/robots.txt",
        status_code=503,
    )
    cache = RobotsCache(http_client=mocked_client)
    fetcher = HttpFetcher(client=mocked_client, robots_cache=cache)
    result = await fetcher.fetch("https://broken.test/anything")
    assert result is None
    # No GET on /anything — only the robots fetch fired.
    non_robots = [r for r in httpx_mock.get_requests() if not r.url.path == "/robots.txt"]
    assert non_robots == []


async def test_robots_cached_per_process(httpx_mock, mocked_client):
    """Second fetch to the same host must NOT re-fetch robots.txt."""
    httpx_mock.add_response(
        method="GET",
        url="https://once.test/robots.txt",
        status_code=200,
        content=PERMISSIVE_ROBOTS.encode(),
    )
    httpx_mock.add_response(
        method="GET",
        url="https://once.test/a",
        status_code=200,
        content=b"a",
    )
    httpx_mock.add_response(
        method="GET",
        url="https://once.test/b",
        status_code=200,
        content=b"b",
    )
    cache = RobotsCache(http_client=mocked_client)
    # Use a no-wait rate limiter so the test runs instantly.
    rl = RateLimiter(min_delay_s=0.0, max_delay_s=0.0)
    fetcher = HttpFetcher(client=mocked_client, robots_cache=cache, rate_limiter=rl)

    assert (await fetcher.fetch("https://once.test/a")) is not None
    assert (await fetcher.fetch("https://once.test/b")) is not None

    robots_requests = [
        r for r in httpx_mock.get_requests() if r.url.path == "/robots.txt"
    ]
    assert len(robots_requests) == 1, (
        f"robots.txt fetched {len(robots_requests)} times; expected 1"
    )


# ---------------------------------------------------------------------------
# Rate limiter

async def test_rate_limiter_first_fetch_no_wait(fake_clock, fake_sleep):
    rl = RateLimiter(min_delay_s=3.0, max_delay_s=6.0, clock=fake_clock, sleep=fake_sleep)
    waited = await rl.acquire("https://example.test")
    assert waited == 0.0
    assert fake_sleep.waits == []


async def test_rate_limiter_second_fetch_same_host_sleeps(fake_clock, fake_sleep):
    rl = RateLimiter(min_delay_s=3.0, max_delay_s=6.0, clock=fake_clock, sleep=fake_sleep)
    await rl.acquire("https://example.test")
    fake_clock.advance(1.0)  # 1s of real-world time has elapsed
    await rl.acquire("https://example.test")
    # Target was 3-6s; we slept ~2-5s (3-6 minus 1 elapsed). Verify a sleep happened.
    assert len(fake_sleep.waits) == 1
    assert 2.0 <= fake_sleep.waits[0] <= 5.0


async def test_rate_limiter_independent_per_host(fake_clock, fake_sleep):
    rl = RateLimiter(min_delay_s=3.0, max_delay_s=6.0, clock=fake_clock, sleep=fake_sleep)
    await rl.acquire("https://host-a.test")
    await rl.acquire("https://host-b.test")
    # Both first hits → no sleeps.
    assert fake_sleep.waits == []


async def test_rate_limiter_target_already_elapsed_no_sleep(fake_clock, fake_sleep):
    rl = RateLimiter(min_delay_s=3.0, max_delay_s=6.0, clock=fake_clock, sleep=fake_sleep)
    await rl.acquire("https://example.test")
    fake_clock.advance(10.0)  # plenty of time passed
    await rl.acquire("https://example.test")
    assert fake_sleep.waits == []


# ---------------------------------------------------------------------------
# Cookies — RFC 6265 domain scoping

async def test_cookies_isolated_by_host(httpx_mock, mocked_client):
    """A cookie set by host A must NOT be sent to host B. httpx's
    cookie jar honors RFC 6265 domain scoping by default; this test
    asserts the invariant at our boundary so a future refactor can't
    accidentally drop it."""
    # Host A sets a cookie.
    httpx_mock.add_response(
        method="GET",
        url="https://a.test/login",
        status_code=200,
        content=b"ok",
        headers={"Set-Cookie": "sess=secret-a; Path=/"},
    )
    # Host A subsequent fetch should send the cookie.
    httpx_mock.add_response(
        method="GET",
        url="https://a.test/again",
        status_code=200,
        content=b"again",
    )
    # Host B fetch must NOT include the cookie.
    httpx_mock.add_response(
        method="GET",
        url="https://b.test/page",
        status_code=200,
        content=b"page",
    )

    rl = RateLimiter(min_delay_s=0.0, max_delay_s=0.0)
    fetcher = make_fetcher(mocked_client, rate_limiter=rl)

    await fetcher.fetch("https://a.test/login")
    await fetcher.fetch("https://a.test/again")
    await fetcher.fetch("https://b.test/page")

    requests = httpx_mock.get_requests()
    # Three GETs (we pre-seeded robots so no /robots.txt requests).
    assert len(requests) == 3
    # First A fetch: no cookie sent (we hadn't received one yet).
    # Second A fetch: cookie should be present.
    # B fetch: cookie must not be present.
    second_a = requests[1]
    b_req = requests[2]
    assert "sess=secret-a" in second_a.headers.get("cookie", "")
    assert "sess=secret-a" not in b_req.headers.get("cookie", "")


# ---------------------------------------------------------------------------
# Network errors → None

async def test_connect_error_returns_none(httpx_mock, mocked_client):
    httpx_mock.add_exception(
        httpx.ConnectError("name resolution failed"),
        url="https://unreachable.test/x",
    )
    fetcher = make_fetcher(mocked_client)
    assert await fetcher.fetch("https://unreachable.test/x") is None


async def test_timeout_returns_none(httpx_mock, mocked_client):
    httpx_mock.add_exception(
        httpx.ReadTimeout("read timed out"),
        url="https://slow.test/x",
    )
    fetcher = make_fetcher(mocked_client)
    assert await fetcher.fetch("https://slow.test/x") is None


# ---------------------------------------------------------------------------
# URL hygiene

async def test_non_http_scheme_returns_none_without_request(
    httpx_mock, mocked_client,
):
    fetcher = make_fetcher(mocked_client)
    assert await fetcher.fetch("file:///etc/passwd") is None
    assert await fetcher.fetch("ftp://anon@example.test/x") is None
    assert len(httpx_mock.get_requests()) == 0


# ---------------------------------------------------------------------------
# Self-identification

async def test_user_agent_self_identifies(httpx_mock, mocked_client):
    httpx_mock.add_response(
        method="GET",
        url="https://example.test/page",
        status_code=200,
        content=b"ok",
    )
    fetcher = make_fetcher(mocked_client)
    await fetcher.fetch("https://example.test/page")
    req = httpx_mock.get_requests()[0]
    assert req.headers["User-Agent"].startswith("FieldBridge-Research/1.0")
    assert "fieldbridge.io/bot" in req.headers["User-Agent"]
