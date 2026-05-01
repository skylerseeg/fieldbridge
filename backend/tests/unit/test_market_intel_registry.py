"""Shape tests for the committed NAPC state portal registry.

The registry JSON is built offline by ``scripts/run_napc_probe.py`` and
checked into the repo. This test suite ONLY validates the file's
structure — it does not hit the network. The 9-portal smoke check
(does ``utahbids.net`` actually respond?) lives in
``docs/market-intel.md`` under "Registry validation" and is a manual
post-probe step, not a CI gate. Network reality should not red-light a
PR.

What we lock in here:

  * Top-level keys: ``probe_run_id``, ``probed_at``, ``agent``, ``states``.
  * 50 USPS state codes as the keys of ``states``.
  * Every per-state entry has ``com``, ``net``, ``primary_url``,
    ``primary_variant``, ``last_changed_run_id``.
  * Every per-variant entry has ``url``, ``status``, ``final_url``,
    ``via_www``.
  * Status values are members of ``ProbeStatus``.
  * ``primary_variant`` is one of ``"com"``, ``"net"``, or ``None``.
  * Every URL field that's set is a valid ``https://`` URL.
  * ``probed_at`` parses as ISO-8601.
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

import pytest

from app.services.market_intel.scrapers.napc_network import registry as registry_module
from app.services.market_intel.scrapers.napc_network.registry import (
    REGISTRY_JSON_PATH,
    REGISTRY_SCHEMA_VERSION,
    US_STATES,
    ProbeStatus,
    load_registry,
)

VALID_STATUSES: frozenset[str] = frozenset(s.value for s in ProbeStatus)
VALID_PRIMARY_VARIANTS: frozenset[str | None] = frozenset({"com", "net", None})


@pytest.fixture(scope="module")
def registry() -> dict:
    if not REGISTRY_JSON_PATH.exists():
        pytest.skip(
            f"registry JSON not committed at {REGISTRY_JSON_PATH}; run "
            f"scripts/run_napc_probe.py to generate it"
        )
    return load_registry()


def _is_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def test_top_level_keys(registry: dict) -> None:
    assert set(registry.keys()) >= {
        "schema_version", "probe_run_id", "probed_at", "agent", "states",
    }
    assert isinstance(registry["probe_run_id"], str) and registry["probe_run_id"]
    # Couple the agent assertion to the source-of-truth constant; if
    # someone changes the UA in registry.py without re-running the probe,
    # this fails and prompts a re-probe rather than letting the JSON drift.
    assert registry["agent"] == registry_module.USER_AGENT


def test_schema_version_matches_module(registry: dict) -> None:
    """Lock the committed JSON's schema_version to the module constant.
    Bump-then-reprobe is the only flow that should change either side."""
    assert registry["schema_version"] == REGISTRY_SCHEMA_VERSION


def test_probed_at_is_iso_8601(registry: dict) -> None:
    # datetime.fromisoformat handles ``+00:00`` offsets in 3.11+.
    parsed = datetime.fromisoformat(registry["probed_at"])
    assert parsed.tzinfo is not None, "probed_at must include timezone offset"


def test_all_50_states_present(registry: dict) -> None:
    states = registry["states"]
    assert isinstance(states, dict)
    assert set(states.keys()) == set(US_STATES), (
        f"missing: {set(US_STATES) - set(states.keys())}; "
        f"extra: {set(states.keys()) - set(US_STATES)}"
    )


@pytest.mark.parametrize("state", US_STATES)
def test_state_entry_shape(registry: dict, state: str) -> None:
    entry = registry["states"][state]
    assert set(entry.keys()) >= {
        "com", "net", "primary_url", "primary_variant", "last_changed_run_id",
    }, f"{state}: missing keys {entry.keys()}"

    for variant in ("com", "net"):
        v = entry[variant]
        assert set(v.keys()) >= {"url", "status", "final_url", "via_www"}, (
            f"{state}.{variant}: keys={v.keys()}"
        )
        assert v["status"] in VALID_STATUSES, (
            f"{state}.{variant}.status={v['status']!r} not in ProbeStatus"
        )
        assert _is_https_url(v["url"]), f"{state}.{variant}.url not https: {v['url']!r}"
        if v["final_url"] is not None:
            assert _is_https_url(v["final_url"]), (
                f"{state}.{variant}.final_url not https: {v['final_url']!r}"
            )
        assert isinstance(v["via_www"], bool)

    assert entry["primary_variant"] in VALID_PRIMARY_VARIANTS, (
        f"{state}.primary_variant={entry['primary_variant']!r}"
    )
    if entry["primary_url"] is not None:
        assert _is_https_url(entry["primary_url"]), (
            f"{state}.primary_url not https: {entry['primary_url']!r}"
        )
        # primary_url and primary_variant are paired: either both set or both null.
        assert entry["primary_variant"] is not None
    else:
        assert entry["primary_variant"] is None

    assert isinstance(entry["last_changed_run_id"], str)
    assert entry["last_changed_run_id"]


def test_at_least_one_state_has_a_primary(registry: dict) -> None:
    """Sanity check: a probe that resolves NO primaries means egress is
    wedged. We expect the bulk of states to have a live portal."""
    primaries = [
        s for s in registry["states"].values() if s["primary_url"] is not None
    ]
    assert len(primaries) > 0, "no state has a primary_url; probe likely broken"
