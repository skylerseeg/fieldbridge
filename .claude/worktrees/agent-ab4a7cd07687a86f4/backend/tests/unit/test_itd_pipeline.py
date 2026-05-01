"""End-to-end test for the ITD pipeline orchestrator.

Strategy:

  * Spin up a fresh ``sqlite+aiosqlite:///:memory:`` async engine.
  * Create all tables via ``Base.metadata.create_all`` (sync,
    pre-engine).
  * Seed the SHARED_NETWORK_TENANT_ID tenant so the FK constraint on
    bid_events / bid_results is satisfiable.
  * Mock ``HttpFetcher`` via ``pytest-httpx`` so:
      - the index URL returns hand-crafted HTML linking to N
        ``abst*.pdf`` URLs whose hostnames are routed to local fake
        URLs, AND
      - each fixture URL returns the bytes of one captured PDF.
  * Run ``ITDPipeline.run_state("ID", db)`` and assert:
      - the counters dict has every documented key,
      - ``written`` matches the number of v1 fixtures fed in,
      - ``skipped_legacy_template`` matches the number of legacy
        fixtures fed in,
      - ``skipped_already_ingested`` is 0 on first run, equal to
        ``written`` on a second run (idempotency contract),
      - the canonical golden fixture's parsed values are present in
        the DB byte-for-byte (regression anchor).

No live network. SQLite-only. Deterministic.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select, text

from app.core.database import Base
from app.core.seed import SHARED_NETWORK_TENANT_ID
from app.models.bid_event import BidEvent
from app.models.bid_result import BidResult
from app.models.tenant import Tenant, TenantKind, SubscriptionTier, TenantStatus
from app.services.market_intel.pipeline import ITDPipeline, _empty_counters
from app.services.market_intel.scrapers._fetcher import HttpFetcher, RateLimiter
from app.services.market_intel.scrapers.state_dot.itd import INDEX_URL


def _make_fast_fetcher() -> HttpFetcher:
    """HttpFetcher with a 0-delay rate limiter so tests don't sleep
    3-6s between requests. Production behavior is exercised by the
    fetcher's own test suite."""
    return HttpFetcher(rate_limiter=RateLimiter(min_delay_s=0.0, max_delay_s=0.0))


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "itd"


# ---------------------------------------------------------------------------
# Fixtures

def _load_manifest_or_skip() -> dict:
    manifest_path = FIXTURES_DIR / "MANIFEST.json"
    if not manifest_path.exists():
        pytest.skip(f"ITD fixtures not committed at {FIXTURES_DIR}")
    return json.loads(manifest_path.read_text())


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Fresh in-memory SQLite, all tables created, shared-network
    tenant seeded."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        # Seed the SHARED_NETWORK_TENANT row so FK constraints hold.
        session.add(
            Tenant(
                id=SHARED_NETWORK_TENANT_ID,
                slug="shared-network",
                company_name="Shared Bid Network",
                contact_email="shared@fieldbridge.test",
                tier=SubscriptionTier.INTERNAL,
                status=TenantStatus.ACTIVE,
                kind=TenantKind.SHARED_DATASET,
            )
        )
        await session.commit()
        yield session

    await engine.dispose()


def _build_index_html(pdf_filenames: list[str]) -> str:
    """Hand-crafted HTML mimicking ITD's contractor-bidding index page.

    Uses absolute URLs that match where pytest-httpx will route the
    PDF responses. Includes a few non-abstract links to verify the
    discovery filter."""
    pdf_links = "\n".join(
        f'<a href="https://apps.itd.idaho.gov/apps/contractors/{name}">{name}</a>'
        for name in pdf_filenames
    )
    return f"""<!DOCTYPE html>
<html><body>
  <a href="https://itd.idaho.gov/about/">About — should be filtered out</a>
  <a href="https://apps.itd.idaho.gov/apps/contractors/NTC25241.pdf">A pre-bid notice — should be filtered</a>
  <a href="https://apps.itd.idaho.gov/apps/contractors/Wage%20Determinations.PDF">Wage rates PDF — should be filtered</a>
  {pdf_links}
</body></html>
"""


def _register_index_response(httpx_mock, pdf_filenames: list[str]) -> None:
    httpx_mock.add_response(
        method="GET",
        url=INDEX_URL,
        status_code=200,
        text=_build_index_html(pdf_filenames),
        headers={"Content-Type": "text/html; charset=utf-8"},
    )


def _register_pdf_response(httpx_mock, filename: str) -> None:
    pdf_path = FIXTURES_DIR / filename
    httpx_mock.add_response(
        method="GET",
        url=f"https://apps.itd.idaho.gov/apps/contractors/{filename}",
        status_code=200,
        content=pdf_path.read_bytes(),
        headers={"Content-Type": "application/pdf"},
    )


def _register_robots(httpx_mock) -> None:
    """Both hosts get permissive robots — itd.idaho.gov has the real
    'Disallow: /wp-admin/' policy, apps.* gets a clean 200."""
    httpx_mock.add_response(
        method="GET",
        url="https://itd.idaho.gov/robots.txt",
        status_code=200,
        text="User-agent: *\nDisallow: /wp-admin/\n",
    )
    httpx_mock.add_response(
        method="GET",
        url="https://apps.itd.idaho.gov/robots.txt",
        status_code=200,
        text="User-agent: *\nAllow: /\n",
    )


# Test seam: a clock that advances 1ms per call so duration_ms is
# deterministic without faking time-of-day.
class _DeterministicClock:
    def __init__(self) -> None:
        self._t = 0.0

    def __call__(self) -> float:
        self._t += 0.001
        return self._t


# ---------------------------------------------------------------------------
# (1) Counters dict shape on empty run

async def test_counters_dict_has_canonical_shape() -> None:
    """n8n logs the counter keys; locking them in here so a future
    rename doesn't silently break the cron run record."""
    counters = _empty_counters()
    expected_keys = {
        "fetched", "parsed", "written",
        "skipped_robots", "skipped_fetch_error",
        "skipped_legacy_template", "skipped_parse_error",
        "skipped_already_ingested",
        "duration_ms",
    }
    assert set(counters.keys()) == expected_keys
    assert all(v == 0 for v in counters.values())


# ---------------------------------------------------------------------------
# (2) Happy E2E: feed 3 v1 + 1 legacy fixture; assert counters + DB

async def test_e2e_writes_v1_skips_legacy(httpx_mock, db_session: AsyncSession):
    manifest = _load_manifest_or_skip()
    v1_fixtures = sorted(
        n for n, rec in manifest["fixtures"].items()
        if rec["template_version"] == "aashtoware_v1"
    )[:3]
    legacy_fixtures = sorted(
        n for n, rec in manifest["fixtures"].items()
        if rec["template_version"] == "itd_legacy"
    )[:1]
    pdf_names = v1_fixtures + legacy_fixtures
    assert len(v1_fixtures) == 3
    assert len(legacy_fixtures) == 1

    _register_robots(httpx_mock)
    _register_index_response(httpx_mock, pdf_names)
    for name in pdf_names:
        _register_pdf_response(httpx_mock, name)

    fetcher = _make_fast_fetcher()
    pipeline = ITDPipeline(fetcher=fetcher, clock=_DeterministicClock())
    try:
        counters = await pipeline.run_state("ID", db_session)
    finally:
        await fetcher.aclose()

    # Counters
    assert counters["fetched"] == 4
    assert counters["parsed"] == 3
    assert counters["written"] == 3
    assert counters["skipped_legacy_template"] == 1
    assert counters["skipped_parse_error"] == 0
    assert counters["skipped_robots"] == 0
    assert counters["skipped_fetch_error"] == 0
    assert counters["skipped_already_ingested"] == 0
    assert counters["duration_ms"] >= 0

    # DB shape
    events = (await db_session.execute(select(BidEvent))).scalars().all()
    results = (await db_session.execute(select(BidResult))).scalars().all()
    assert len(events) == 3
    assert len(results) >= 6  # every event has ≥2 bidders in our fixtures

    # Every event has the right tenant + network metadata.
    for ev in events:
        assert ev.tenant_id == SHARED_NETWORK_TENANT_ID
        assert ev.source_network == "state_dot_itd"
        assert ev.source_state == "ID"
        assert ev.bid_status == "awarded"
        assert ev.raw_html_hash and len(ev.raw_html_hash) == 64
        assert ev.location_state == "ID"

    # All bidder rows are tenant-scoped + linked to a parent event.
    event_ids = {ev.id for ev in events}
    for r in results:
        assert r.tenant_id == SHARED_NETWORK_TENANT_ID
        assert r.bid_event_id in event_ids


# ---------------------------------------------------------------------------
# (3) Idempotency: re-running on the same data is a no-op

async def test_idempotent_rerun(httpx_mock, db_session: AsyncSession):
    """Second run with identical fetched bytes → 0 new writes, all
    skipped_already_ingested. Documents that the unique constraint
    on (tenant_id, source_url, raw_html_hash) is honored end-to-end."""
    manifest = _load_manifest_or_skip()
    v1_fixtures = sorted(
        n for n, rec in manifest["fixtures"].items()
        if rec["template_version"] == "aashtoware_v1"
    )[:2]

    # Robots cache survives across runs → register once. Index page +
    # each PDF: register the response twice because both pipeline runs
    # fetch them (the cache only covers robots).
    _register_robots(httpx_mock)
    for _ in range(2):
        _register_index_response(httpx_mock, v1_fixtures)
        for name in v1_fixtures:
            _register_pdf_response(httpx_mock, name)

    fetcher = _make_fast_fetcher()
    pipeline = ITDPipeline(fetcher=fetcher, clock=_DeterministicClock())
    try:
        first = await pipeline.run_state("ID", db_session)
        second = await pipeline.run_state("ID", db_session)
    finally:
        await fetcher.aclose()

    assert first["written"] == 2
    assert first["skipped_already_ingested"] == 0
    assert second["written"] == 0
    assert second["skipped_already_ingested"] == 2
    assert second["fetched"] == 2  # we still fetched, just didn't write

    # DB row count is unchanged across runs.
    events = (await db_session.execute(select(BidEvent))).scalars().all()
    assert len(events) == 2


# ---------------------------------------------------------------------------
# (4) Golden: golden fixture's parsed fields land in the DB exactly

async def test_golden_abst25183_round_trip(httpx_mock, db_session: AsyncSession):
    GOLDEN = "abst25183.pdf"
    _register_robots(httpx_mock)
    _register_index_response(httpx_mock, [GOLDEN])
    _register_pdf_response(httpx_mock, GOLDEN)

    fetcher = _make_fast_fetcher()
    pipeline = ITDPipeline(fetcher=fetcher, clock=_DeterministicClock())
    try:
        counters = await pipeline.run_state("ID", db_session)
    finally:
        await fetcher.aclose()

    assert counters["written"] == 1

    event = (await db_session.execute(select(BidEvent))).scalars().one()
    assert event.tenant_id == SHARED_NETWORK_TENANT_ID
    assert event.source_url == f"https://apps.itd.idaho.gov/apps/contractors/{GOLDEN}"
    assert event.source_network == "state_dot_itd"
    assert event.source_state == "ID"
    assert event.solicitation_id == "25183260303"
    assert event.project_title == "I-15, RIVERTON ROAD BRIDGE"
    assert event.project_owner == "Idaho Transportation Department"
    assert event.work_scope == "I-15, RIVERTON ROAD BRIDGE"
    assert event.location_county == "Bingham"
    assert event.location_state == "ID"
    assert event.bid_status == "awarded"
    assert event.bid_open_date.isoformat() == "2026-04-14"

    results = (
        await db_session.execute(
            select(BidResult)
            .where(BidResult.bid_event_id == event.id)
            .order_by(BidResult.rank)
        )
    ).scalars().all()
    assert len(results) == 2

    low, runner_up = results
    assert low.rank == 1
    assert low.contractor_name == "CANNON BUILDERS, INC."
    assert float(low.bid_amount) == pytest.approx(10_500_921.46)
    assert low.is_low_bidder is True
    assert low.is_awarded is True

    assert runner_up.rank == 2
    assert runner_up.contractor_name == "WADSWORTH BROTHERS CONSTRUCTION COMPANY, INC."
    assert float(runner_up.bid_amount) == pytest.approx(15_677_191.36)
    assert runner_up.is_low_bidder is False
    # Irregular Bid → not awarded; the parser captured this in slice 2's
    # ParsedBidder.notes which the pipeline does not propagate to the
    # ORM (no notes column on bid_results). The is_awarded=False flag
    # is the durable signal.
    assert runner_up.is_awarded is False


# ---------------------------------------------------------------------------
# (5) URL discovery filtering — non-abstract links are dropped

async def test_url_discovery_filters_non_abstracts(
    httpx_mock, db_session: AsyncSession,
):
    """The hand-crafted index HTML includes deliberate non-abstract
    links (an /about/, an NTC pre-bid PDF, a Wage Determinations PDF).
    None of them should surface in the fetcher's URL list — verified
    by the absence of fetcher-error counters and by zero registered
    response leaks."""
    manifest = _load_manifest_or_skip()
    v1_fixtures = sorted(
        n for n, rec in manifest["fixtures"].items()
        if rec["template_version"] == "aashtoware_v1"
    )[:1]

    _register_robots(httpx_mock)
    _register_index_response(httpx_mock, v1_fixtures)
    _register_pdf_response(httpx_mock, v1_fixtures[0])
    # Note: deliberately do NOT register the non-abstract URLs. If the
    # discovery filter is wrong and we try to fetch them, pytest-httpx
    # will raise on the unmocked request and fail the test.

    fetcher = _make_fast_fetcher()
    pipeline = ITDPipeline(fetcher=fetcher, clock=_DeterministicClock())
    try:
        counters = await pipeline.run_state("ID", db_session)
    finally:
        await fetcher.aclose()

    assert counters["fetched"] == 1
    assert counters["written"] == 1


# ---------------------------------------------------------------------------
# (6) Index-fetch failure → graceful empty run

async def test_index_fetch_failure_returns_empty_counters(
    httpx_mock, db_session: AsyncSession,
):
    """If the index page itself fails (5xx, network), the pipeline
    must return cleanly with zero counters — n8n logs an empty run
    rather than seeing an exception."""
    # Only itd.idaho.gov robots is needed; apps.* is never reached
    # because the index fetch aborts the run.
    httpx_mock.add_response(
        method="GET",
        url="https://itd.idaho.gov/robots.txt",
        status_code=200,
        text="User-agent: *\nDisallow: /wp-admin/\n",
    )
    httpx_mock.add_response(
        method="GET",
        url=INDEX_URL,
        status_code=503,
    )

    fetcher = _make_fast_fetcher()
    pipeline = ITDPipeline(fetcher=fetcher, clock=_DeterministicClock())
    try:
        counters = await pipeline.run_state("ID", db_session)
    finally:
        await fetcher.aclose()

    assert counters["fetched"] == 0
    assert counters["written"] == 0
    # Still has all canonical keys.
    assert "duration_ms" in counters
    assert "skipped_robots" in counters


# ---------------------------------------------------------------------------
# (7) Wrong-state ValueError

async def test_run_state_rejects_non_id_state(db_session: AsyncSession):
    pipeline = ITDPipeline(fetcher=_make_fast_fetcher(), clock=_DeterministicClock())
    try:
        with pytest.raises(ValueError, match="ITDPipeline only handles"):
            await pipeline.run_state("UT", db_session)
    finally:
        await pipeline._fetcher.aclose()
