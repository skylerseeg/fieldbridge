"""HEAD-probe registry for NAPC ``{state}bids.{com,net}`` portals.

Two responsibilities:

  1. ``probe_all_states()`` — async, hits every state's ``.com`` and
     ``.net`` apex once, classifies the response, and produces a
     committable JSON snapshot.
  2. ``load_registry()`` — synchronous read of the committed snapshot,
     used by the (future) Fetcher to decide which URL to crawl per
     state.

The committed JSON at ``state_portal_registry.json`` is the source of
truth. Python module constants drift; reviewed JSON does not. Re-run
the probe periodically; commit the diff.

Probe etiquette (matches the broader scraper rules):

  * Self-identifies as ``FieldBridge-Research/1.0 (+https://fieldbridge.io/bot)``
  * Rate-limited to <= 1 request per 3-6 seconds **per host** (each
    state has two hosts, so we serialize them).
  * No robots.txt fetch — apex GET for liveness is not a crawl. Robots
    is a Fetcher-level concern for the next slice.

Why GET, not HEAD: the brief originally specified a HEAD-probe registry
for low impact, but a single GET to the apex root is the same shape of
load (one request per variant, no crawl) and gives us two signals HEAD
cannot:

  * **Parked-domain detection.** ``utahbids.com`` returns HTTP 200 with
    a 114-byte JS-redirect to ``/lander`` (sav.com-style domain
    parking). HEAD can't distinguish that from the real portal.
  * **Apex-vs-www certificate scoping.** ``idahobids.com`` ships a TLS
    cert valid only for ``www.idahobids.com``; the apex itself fails
    SSL verification. A GET retry against the ``www.`` host is the
    natural recovery path.

The probe still hits each host exactly twice (.com + .net) at one
request per 3-6 seconds, so the etiquette envelope is unchanged.

Probe runner: ``backend/scripts/run_napc_probe.py``.
Smoke check (9 manually-verified portals): see
``docs/market-intel.md`` -> "Registry validation".
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import ssl
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("fieldbridge.market_intel.registry")

# All 50 USPS state codes. DC and territories are out of scope for v1.5.
US_STATES: tuple[str, ...] = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
)

# Per-state stem overrides for NAPC's known naming exceptions. Looked
# up first; falls back to the canonical state-name map below.
#
# 2026-04-29 — MA uses ``massbids.net`` (43 KB live NAPC portal); the
# algorithmic ``massachusettsbids.{com,net}`` stems both DNS-fail and
# ``mabids.com`` is parked. Add new overrides here as they're
# discovered, with a date + verification note.
_STATE_STEM_OVERRIDES: dict[str, str] = {
    "MA": "mass",
}


# Map USPS code -> NAPC subdomain stem. NAPC uses full state names
# (no abbreviations) for these portals: utahbids, idahobids, etc.
_STATE_NAME_STEM: dict[str, str] = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas",
    "CA": "california", "CO": "colorado", "CT": "connecticut", "DE": "delaware",
    "FL": "florida", "GA": "georgia", "HI": "hawaii", "ID": "idaho",
    "IL": "illinois", "IN": "indiana", "IA": "iowa", "KS": "kansas",
    "KY": "kentucky", "LA": "louisiana", "ME": "maine", "MD": "maryland",
    "MA": "massachusetts", "MI": "michigan", "MN": "minnesota",
    "MS": "mississippi", "MO": "missouri", "MT": "montana", "NE": "nebraska",
    "NV": "nevada", "NH": "newhampshire", "NJ": "newjersey", "NM": "newmexico",
    "NY": "newyork", "NC": "northcarolina", "ND": "northdakota", "OH": "ohio",
    "OK": "oklahoma", "OR": "oregon", "PA": "pennsylvania", "RI": "rhodeisland",
    "SC": "southcarolina", "SD": "southdakota", "TN": "tennessee", "TX": "texas",
    "UT": "utah", "VT": "vermont", "VA": "virginia", "WA": "washington",
    "WV": "westvirginia", "WI": "wisconsin", "WY": "wyoming",
}

USER_AGENT = "FieldBridge-Research/1.0 (+https://fieldbridge.io/bot)"
REQUEST_TIMEOUT_S = 15.0
# Per-host delay range. The probe serializes the two variants (.com,
# then .net) for a given state, so the smaller of these two values
# governs the per-host pace.
RATE_LIMIT_MIN_S = 3.0
RATE_LIMIT_MAX_S = 6.0

REGISTRY_JSON_PATH: Path = Path(__file__).parent / "state_portal_registry.json"


class ProbeStatus(str, Enum):
    """Classification of a single apex GET.

    Selection precedence for ``primary_url`` (highest first):
        LIVE_200 > LIVE_REDIRECT > BLOCKED_403 > anything else (-> null)

    A 403 means the host is alive but rejected our request; it's a
    candidate worth crawling with the real Fetcher in the next slice,
    not a confirmed live portal.

    LIVE_PARKED is explicitly NOT in the primary preference. The apex
    returned 200 but the body matches a domain-parking signature
    (small body + JS redirect to ``/lander``, ``parked``,
    ``buy this domain``, etc.). The host is technically live but
    serves no portal content.
    """

    LIVE_200 = "200"
    LIVE_REDIRECT = "3xx_resolved"
    LIVE_PARKED = "200_parked"
    BLOCKED_403 = "403_blocked"
    NOT_FOUND_404 = "404"
    TIMEOUT = "timeout"
    SSL_ERROR = "ssl_error"
    DNS_FAIL = "dns_fail"
    OTHER_4XX = "other_4xx"
    OTHER_5XX = "other_5xx"
    UNKNOWN = "unknown"


# Ordered preference for primary_variant selection. A status not in
# this tuple disqualifies the variant from being primary.
_PRIMARY_PREFERENCE: tuple[ProbeStatus, ...] = (
    ProbeStatus.LIVE_200,
    ProbeStatus.LIVE_REDIRECT,
    ProbeStatus.BLOCKED_403,
)

# Heuristic body inspection. A real NAPC portal page is ~40 KB of
# HTML; a parked apex is typically <2 KB. Combine size with a
# substring match against known parking signatures so a small but
# real "under construction" portal stub doesn't get false-flagged.
_PARKED_BODY_MAX_LEN = 2000
_PARKING_SIGNATURES: tuple[str, ...] = (
    '/lander',
    'window.location.href="/lander"',
    "parkingcrew",
    "parked-domain",
    "buy this domain",
    "domain is for sale",
    "this domain is parked",
    "domainmarket",
)


def _candidate_urls(state: str) -> tuple[tuple[str, str], tuple[str, str]]:
    """Return ((com_variant, com_url), (net_variant, net_url)) for ``state``.

    Honors ``_STATE_STEM_OVERRIDES`` first, then falls back to the
    canonical state-name stem.
    """
    stem = _STATE_STEM_OVERRIDES.get(state, _STATE_NAME_STEM[state])
    return (
        ("com", f"https://{stem}bids.com"),
        ("net", f"https://{stem}bids.net"),
    )


def _looks_parked(body: str) -> bool:
    """Heuristic: does this 200 body look like a domain-parking page?

    True only if body is small AND contains a parking signature, so a
    legit short response (e.g. "<h1>Site coming soon</h1>") is not
    misclassified.
    """
    if not body or len(body) > _PARKED_BODY_MAX_LEN:
        return False
    lower = body.lower()
    return any(sig in lower for sig in _PARKING_SIGNATURES)


def _classify_connect_error(exc: BaseException) -> ProbeStatus:
    """Map an httpx connect-layer exception onto a ProbeStatus."""
    msg = str(exc).lower()
    if "ssl" in msg or "certificate" in msg or "tls" in msg:
        return ProbeStatus.SSL_ERROR
    if (
        "name or service not known" in msg
        or "nodename nor servname" in msg
        or "getaddrinfo failed" in msg
        or "no address associated" in msg
        or "temporary failure in name resolution" in msg
    ):
        return ProbeStatus.DNS_FAIL
    return ProbeStatus.DNS_FAIL


async def _get_one(
    client: httpx.AsyncClient,
    url: str,
) -> tuple[ProbeStatus, str | None]:
    """Single GET against ``url``. Returns (status, final_url|None)."""
    try:
        resp = await client.get(url)
    except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout):
        return ProbeStatus.TIMEOUT, None
    except (ssl.SSLError, httpx.ConnectError) as exc:
        return _classify_connect_error(exc), None
    except httpx.HTTPError as exc:
        log.warning("probe %s raised %s: %s", url, type(exc).__name__, exc)
        return ProbeStatus.UNKNOWN, None

    final_url = str(resp.url)
    code = resp.status_code

    if code == 200:
        body = resp.text or ""
        if _looks_parked(body):
            return ProbeStatus.LIVE_PARKED, final_url
        # If httpx followed redirects, we got a 200 at final_url; flag
        # 3xx_resolved when the final URL differs from the request URL.
        if final_url.rstrip("/") != url.rstrip("/"):
            return ProbeStatus.LIVE_REDIRECT, final_url
        return ProbeStatus.LIVE_200, final_url
    if code == 403:
        return ProbeStatus.BLOCKED_403, final_url
    if code == 404:
        return ProbeStatus.NOT_FOUND_404, None
    if 400 <= code < 500:
        return ProbeStatus.OTHER_4XX, final_url
    if 500 <= code < 600:
        return ProbeStatus.OTHER_5XX, final_url
    return ProbeStatus.UNKNOWN, final_url


def _www_variant(url: str) -> str | None:
    """Return ``https://www.{host}{path}`` if ``url`` is on a bare apex.

    Returns None if the URL already has a ``www.`` prefix (no
    second-level fallback)."""
    # Cheap parse: we only generate https://{host} URLs in this
    # module, so a substring rewrite is safe.
    prefix = "https://"
    if not url.startswith(prefix):
        return None
    rest = url[len(prefix):]
    if rest.startswith("www."):
        return None
    return f"{prefix}www.{rest}"


async def _probe_one(
    client: httpx.AsyncClient,
    url: str,
) -> tuple[ProbeStatus, str | None, bool]:
    """Probe ``url``, falling back to the ``www.`` host on SSL/DNS
    failure. Returns (status, final_url|None, via_www).

    The fallback only triggers on ssl_error / dns_fail because those
    are the failure modes a www subdomain can plausibly fix (cert
    scoped to www, or apex DNS missing while www exists). Every other
    status is returned as-is.
    """
    status, final = await _get_one(client, url)
    if status not in (ProbeStatus.SSL_ERROR, ProbeStatus.DNS_FAIL):
        return status, final, False

    www_url = _www_variant(url)
    if www_url is None:
        return status, final, False

    log.debug("apex %s -> %s, retrying %s", url, status.value, www_url)
    status_www, final_www = await _get_one(client, www_url)
    # Only treat the www attempt as success if it lands in primary
    # preference; otherwise keep the original (more honest) failure.
    if status_www in _PRIMARY_PREFERENCE:
        return status_www, final_www, True
    return status, final, False


def _select_primary(
    com_status: ProbeStatus,
    com_final: str | None,
    com_url: str,
    net_status: ProbeStatus,
    net_final: str | None,
    net_url: str,
) -> tuple[str | None, str | None]:
    """Pick (primary_url, primary_variant) per the precedence rules."""
    candidates: list[tuple[int, str, str]] = []
    for status, final, url, variant in (
        (com_status, com_final, com_url, "com"),
        (net_status, net_final, net_url, "net"),
    ):
        if status not in _PRIMARY_PREFERENCE:
            continue
        rank = _PRIMARY_PREFERENCE.index(status)
        chosen_url = final or url
        candidates.append((rank, chosen_url, variant))
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1], candidates[0][2]


async def probe_state(
    state: str,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    """Probe both NAPC variants for ``state``. Returns a dict shaped
    like one entry of the committed registry's ``states`` map (no
    ``last_changed_run_id`` — that's filled in by the runner when it
    diffs against the prior committed registry)."""
    (_, com_url), (_, net_url) = _candidate_urls(state)

    com_status, com_final, com_via_www = await _probe_one(client, com_url)
    # Per-host rate limit: serialize com -> net for the same host class.
    await asyncio.sleep(random.uniform(RATE_LIMIT_MIN_S, RATE_LIMIT_MAX_S))
    net_status, net_final, net_via_www = await _probe_one(client, net_url)

    primary_url, primary_variant = _select_primary(
        com_status, com_final, com_url,
        net_status, net_final, net_url,
    )

    return {
        "com": {
            "url": com_url,
            "status": com_status.value,
            "final_url": com_final,
            "via_www": com_via_www,
        },
        "net": {
            "url": net_url,
            "status": net_status.value,
            "final_url": net_final,
            "via_www": net_via_www,
        },
        "primary_url": primary_url,
        "primary_variant": primary_variant,
    }


async def probe_all_states(
    states: tuple[str, ...] = US_STATES,
) -> dict[str, Any]:
    """Probe every state. Returns the full registry payload, ready to
    be JSON-dumped. Does NOT write to disk — that's the runner's job
    (so the runner can also compute ``last_changed_run_id`` against
    the prior committed registry)."""
    probe_run_id = str(uuid.uuid4())
    probed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    timeout = httpx.Timeout(REQUEST_TIMEOUT_S, connect=REQUEST_TIMEOUT_S)
    limits = httpx.Limits(max_connections=4, max_keepalive_connections=2)

    states_out: dict[str, Any] = {}

    async with httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        limits=limits,
        follow_redirects=True,
    ) as client:
        for i, state in enumerate(states):
            log.info("probing %s (%d/%d)", state, i + 1, len(states))
            states_out[state] = await probe_state(state, client)
            # Inter-state delay (separate state = different host pair, so
            # this is a softer politeness gate, not strict per-host rate
            # limiting).
            if i < len(states) - 1:
                await asyncio.sleep(random.uniform(RATE_LIMIT_MIN_S, RATE_LIMIT_MAX_S))

    return {
        "probe_run_id": probe_run_id,
        "probed_at": probed_at,
        "agent": USER_AGENT,
        "states": states_out,
    }


def merge_with_prior(
    new_registry: dict[str, Any],
    prior_registry: dict[str, Any] | None,
) -> dict[str, Any]:
    """Stamp ``last_changed_run_id`` on each state.

    For a state present in ``prior_registry`` whose probe outcome is
    unchanged, carry the prior ``last_changed_run_id`` forward. When
    the outcome changes (or the state is new), set it to the current
    run id. This makes a diff between two committed registries trivially
    inspectable: any state whose ``last_changed_run_id`` matches the
    file's ``probe_run_id`` is one that moved this run.
    """
    new_run_id: str = new_registry["probe_run_id"]
    prior_states = (prior_registry or {}).get("states", {})

    for state, entry in new_registry["states"].items():
        prior = prior_states.get(state)
        if prior is None or _state_outcome_changed(prior, entry):
            entry["last_changed_run_id"] = new_run_id
        else:
            entry["last_changed_run_id"] = prior.get(
                "last_changed_run_id", new_run_id
            )

    return new_registry


def _state_outcome_changed(prior: dict[str, Any], current: dict[str, Any]) -> bool:
    """Return True if the meaningful fields changed.

    'Meaningful' = the per-variant status, the per-variant final_url,
    and the primary_url/primary_variant. Bookkeeping fields like
    ``last_changed_run_id`` itself are ignored."""
    for variant in ("com", "net"):
        p = prior.get(variant) or {}
        c = current.get(variant) or {}
        if p.get("status") != c.get("status"):
            return True
        if p.get("final_url") != c.get("final_url"):
            return True
        if bool(p.get("via_www")) != bool(c.get("via_www")):
            return True
    if prior.get("primary_url") != current.get("primary_url"):
        return True
    if prior.get("primary_variant") != current.get("primary_variant"):
        return True
    return False


def load_registry(path: Path = REGISTRY_JSON_PATH) -> dict[str, Any]:
    """Read the committed registry from disk."""
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_registry(registry: dict[str, Any], path: Path = REGISTRY_JSON_PATH) -> None:
    """Write a registry payload to disk with stable formatting (sorted
    state keys, 2-space indent, trailing newline)."""
    states = registry["states"]
    registry["states"] = dict(sorted(states.items()))
    with path.open("w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)
        f.write("\n")
