"""Tests for ``app.modules.market_intel.service`` analytics queries.

Pattern: same as ``test_itd_pipeline.py`` — fresh ``aiosqlite``
in-memory engine, ``Base.metadata.create_all``, seed
``SHARED_NETWORK_TENANT_ID`` + a customer tenant, populate via the
slice-4a pipeline using captured fixtures (mocked through
``pytest-httpx``), then call each service function and assert on
output shape + tenant-union behavior.

What we lock in:

  * **Shape**: every returned row matches the Pydantic schema
    (Pydantic itself enforces this, but we assert types + ranges
    that aren't part of the schema constraint).
  * **Tenant union**: a customer tenant calls the service. The
    rows under SHARED_NETWORK_TENANT_ID still appear in results —
    that's the cross-tenant network read pattern.
  * **Filters**: states / months_back / min_bids / bid_min/max /
    contractor pattern all filter as documented.
  * **Empty-input safety**: no fixtures populated → every service
    returns ``[]`` cleanly (no IndexError, no division-by-zero).

We do NOT test the SQL math row-by-row against hand-computed
expected values — slice 2 + 4a's golden tests cover field-level
correctness on the parser/pipeline side, and the service is a
thin GROUP BY + statistics.median pass on top of those rows.
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.seed import SHARED_NETWORK_TENANT_ID
from app.models.bid_event import BidEvent
from app.models.bid_result import BidResult
from app.models.tenant import (
    SubscriptionTier,
    Tenant,
    TenantKind,
    TenantStatus,
)
from app.modules.market_intel.schema import (
    CalibrationPoint,
    CompetitorCurveRow,
    OpportunityRow,
)
from app.modules.market_intel.service import (
    _quarter_start,
    get_bid_calibration,
    get_competitor_curves,
    get_opportunity_gaps,
)
from app.services.market_intel.pipeline import ITDPipeline
from app.services.market_intel.scrapers._fetcher import HttpFetcher, RateLimiter
from app.services.market_intel.scrapers.state_dot.itd import INDEX_URL


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "itd"


# ---------------------------------------------------------------------------
# Helpers (lifted from test_itd_pipeline.py — same pattern)

def _make_fast_fetcher() -> HttpFetcher:
    return HttpFetcher(rate_limiter=RateLimiter(min_delay_s=0.0, max_delay_s=0.0))


def _load_manifest_or_skip() -> dict:
    manifest_path = FIXTURES_DIR / "MANIFEST.json"
    if not manifest_path.exists():
        pytest.skip(f"ITD fixtures not committed at {FIXTURES_DIR}")
    return json.loads(manifest_path.read_text())


CUSTOMER_TENANT_ID = str(uuid.uuid4())  # stable for test lifetime


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        # Shared-network tenant (where ITDPipeline writes).
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
        # Customer tenant (the caller — proves the cross-tenant union).
        session.add(
            Tenant(
                id=CUSTOMER_TENANT_ID,
                slug="customer-test",
                company_name="Customer Test Co",
                contact_email="customer@fieldbridge.test",
                tier=SubscriptionTier.STARTER,
                status=TenantStatus.ACTIVE,
                kind=TenantKind.CUSTOMER,
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


def _build_index_html(pdf_filenames: list[str]) -> str:
    pdf_links = "\n".join(
        f'<a href="https://apps.itd.idaho.gov/apps/contractors/{name}">{name}</a>'
        for name in pdf_filenames
    )
    return f"<html><body>{pdf_links}</body></html>"


def _register_robots(httpx_mock) -> None:
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


def _register_index(httpx_mock, pdf_filenames: list[str]) -> None:
    httpx_mock.add_response(
        method="GET",
        url=INDEX_URL,
        status_code=200,
        text=_build_index_html(pdf_filenames),
        headers={"Content-Type": "text/html; charset=utf-8"},
    )


def _register_pdf(httpx_mock, filename: str) -> None:
    pdf_path = FIXTURES_DIR / filename
    httpx_mock.add_response(
        method="GET",
        url=f"https://apps.itd.idaho.gov/apps/contractors/{filename}",
        status_code=200,
        content=pdf_path.read_bytes(),
        headers={"Content-Type": "application/pdf"},
    )


async def _populate_via_pipeline(
    httpx_mock, db_session: AsyncSession, fixture_names: list[str],
) -> dict[str, int]:
    """Drive the slice-4a pipeline end-to-end against ``fixture_names``
    so the service tests run against realistic populated DB state."""
    _register_robots(httpx_mock)
    _register_index(httpx_mock, fixture_names)
    for name in fixture_names:
        _register_pdf(httpx_mock, name)
    fetcher = _make_fast_fetcher()
    pipeline = ITDPipeline(fetcher=fetcher)
    try:
        return await pipeline.run_state("ID", db_session)
    finally:
        await fetcher.aclose()


def _v1_fixtures(n: int) -> list[str]:
    manifest = _load_manifest_or_skip()
    return sorted(
        name for name, rec in manifest["fixtures"].items()
        if rec["template_version"] == "aashtoware_v1"
    )[:n]


# ---------------------------------------------------------------------------
# Empty-DB safety

async def test_competitor_curves_empty_db(db_session: AsyncSession):
    out = await get_competitor_curves(
        db_session,
        states=["ID", "UT"],
        months_back=36,
        min_bids=1,
        tenant_id=CUSTOMER_TENANT_ID,
    )
    assert out == []


async def test_opportunity_gaps_empty_db(db_session: AsyncSession):
    out = await get_opportunity_gaps(
        db_session,
        bid_min=0,
        bid_max=10**9,
        months_back=36,
        tenant_id=CUSTOMER_TENANT_ID,
    )
    assert out == []


async def test_bid_calibration_empty_db(db_session: AsyncSession):
    out = await get_bid_calibration(
        db_session,
        contractor_name_match="cannon",
        tenant_id=CUSTOMER_TENANT_ID,
    )
    assert out == []


async def test_competitor_curves_empty_states_returns_empty(db_session: AsyncSession):
    """No state filter passed → return [] without hitting SQL."""
    out = await get_competitor_curves(
        db_session,
        states=[],
        months_back=36,
        min_bids=1,
        tenant_id=CUSTOMER_TENANT_ID,
    )
    assert out == []


# ---------------------------------------------------------------------------
# Quarter helper

@pytest.mark.parametrize(
    "input_date,expected",
    [
        (date(2026, 1, 1), date(2026, 1, 1)),
        (date(2026, 1, 31), date(2026, 1, 1)),
        (date(2026, 3, 31), date(2026, 1, 1)),
        (date(2026, 4, 1), date(2026, 4, 1)),
        (date(2026, 6, 30), date(2026, 4, 1)),
        (date(2026, 7, 1), date(2026, 7, 1)),
        (date(2026, 9, 30), date(2026, 7, 1)),
        (date(2026, 10, 1), date(2026, 10, 1)),
        (date(2026, 12, 31), date(2026, 10, 1)),
    ],
)
def test_quarter_start(input_date: date, expected: date) -> None:
    assert _quarter_start(input_date) == expected


# ---------------------------------------------------------------------------
# Populated DB: shape + tenant-union assertions

async def test_competitor_curves_returns_shaped_rows(
    httpx_mock, db_session: AsyncSession,
):
    """Populate via pipeline (writes under SHARED_NETWORK_TENANT_ID),
    query as the customer tenant, assert rows came back."""
    fixtures = _v1_fixtures(5)
    counters = await _populate_via_pipeline(httpx_mock, db_session, fixtures)
    assert counters["written"] == 5

    # months_back has to span back to the fixture letting dates (2026
    # range). Use a generous window since fixtures pre-date today.
    out = await get_competitor_curves(
        db_session,
        states=["ID"],
        months_back=240,  # ~20 years
        min_bids=1,
        tenant_id=CUSTOMER_TENANT_ID,
    )

    # Shape
    assert len(out) > 0
    assert all(isinstance(r, CompetitorCurveRow) for r in out)
    for r in out:
        assert r.contractor_name and r.contractor_name.strip()
        assert r.bid_count >= 1
        assert 0.0 <= r.win_rate <= 1.0
        # avg_premium_over_low can be 0.0 (low bidders) or positive.
        assert r.avg_premium_over_low >= 0.0
        # median_rank is 1.0 minimum (rank-1 is lowest possible).
        assert r.median_rank >= 1.0

    # Tenant union: rows live under the shared sentinel; the customer
    # tenant sees them. Sanity check by also calling with
    # tenant_id=SHARED_NETWORK_TENANT_ID — should return identical
    # contractor list.
    out_shared = await get_competitor_curves(
        db_session,
        states=["ID"],
        months_back=240,
        min_bids=1,
        tenant_id=SHARED_NETWORK_TENANT_ID,
    )
    assert {r.contractor_name for r in out} == {r.contractor_name for r in out_shared}


async def test_competitor_curves_min_bids_filter(
    httpx_mock, db_session: AsyncSession,
):
    """Crank ``min_bids`` high enough that no contractor qualifies."""
    fixtures = _v1_fixtures(3)
    await _populate_via_pipeline(httpx_mock, db_session, fixtures)
    out = await get_competitor_curves(
        db_session,
        states=["ID"],
        months_back=240,
        min_bids=999,
        tenant_id=CUSTOMER_TENANT_ID,
    )
    assert out == []


async def test_competitor_curves_state_filter(
    httpx_mock, db_session: AsyncSession,
):
    """Query for a non-Idaho state — the seeded fixtures are all ID,
    so the filter should yield zero rows."""
    fixtures = _v1_fixtures(3)
    await _populate_via_pipeline(httpx_mock, db_session, fixtures)
    out = await get_competitor_curves(
        db_session,
        states=["WY", "MT"],  # neither is in our fixtures
        months_back=240,
        min_bids=1,
        tenant_id=CUSTOMER_TENANT_ID,
    )
    assert out == []


async def test_competitor_curves_low_bidder_premium_is_zero(
    httpx_mock, db_session: AsyncSession,
):
    """A contractor that only ever shows up at rank 1 has
    avg_premium_over_low = 0.0 (no markup over themselves)."""
    fixtures = _v1_fixtures(8)
    await _populate_via_pipeline(httpx_mock, db_session, fixtures)
    out = await get_competitor_curves(
        db_session,
        states=["ID"],
        months_back=240,
        min_bids=1,
        tenant_id=CUSTOMER_TENANT_ID,
    )
    # Find any contractor whose every bid was the low — its premium
    # should be exactly 0.0 (we include the low bidder's own row at
    # premium=0). Test only fires if such a contractor exists in the
    # 8 fixtures; if not, skip the assertion silently.
    always_low = [r for r in out if r.win_rate == 1.0]
    for r in always_low:
        assert r.avg_premium_over_low == pytest.approx(0.0)
        assert r.median_rank == 1.0


async def test_opportunity_gaps_returns_shaped_rows(
    httpx_mock, db_session: AsyncSession,
):
    fixtures = _v1_fixtures(5)
    await _populate_via_pipeline(httpx_mock, db_session, fixtures)
    out = await get_opportunity_gaps(
        db_session,
        bid_min=0,
        bid_max=10**9,
        months_back=240,
        tenant_id=CUSTOMER_TENANT_ID,
    )
    assert len(out) > 0
    for r in out:
        assert isinstance(r, OpportunityRow)
        assert len(r.state) == 2
        assert r.missed_count >= 1
        assert r.avg_low_bid >= 0.0
        assert r.top_scope_codes == []  # csi_codes deferred to v1.5b normalizer


async def test_opportunity_gaps_bid_range_filter(
    httpx_mock, db_session: AsyncSession,
):
    """Tight bid range that excludes everything → empty result."""
    fixtures = _v1_fixtures(3)
    await _populate_via_pipeline(httpx_mock, db_session, fixtures)
    out = await get_opportunity_gaps(
        db_session,
        bid_min=10**11,  # $100B — comfortably above any real bid;
        bid_max=10**12,  # below SQLite's signed-int64 max (9.2e18)
        months_back=240,
        tenant_id=CUSTOMER_TENANT_ID,
    )
    assert out == []


async def test_bid_calibration_returns_shaped_rows(
    httpx_mock, db_session: AsyncSession,
):
    """Match a contractor that appears in the fixtures. STAKER & PARSON
    appears in abst21845 (rank 3, multi-line name) and abst21951
    (rank 2) — both in the first 5 sorted v1 fixtures."""
    await _populate_via_pipeline(httpx_mock, db_session, _v1_fixtures(5))
    out = await get_bid_calibration(
        db_session,
        contractor_name_match="staker",
        tenant_id=CUSTOMER_TENANT_ID,
    )
    assert len(out) > 0
    for r in out:
        assert isinstance(r, CalibrationPoint)
        # quarter is the first day of a calendar quarter (1, 4, 7, or 10).
        assert r.quarter.day == 1
        assert r.quarter.month in (1, 4, 7, 10)
        assert r.bids_submitted >= 1
        assert 0 <= r.wins <= r.bids_submitted
        assert r.avg_rank >= 1.0
        # pct_above_low can be None (only-low-bidder quarter) or float.
        if r.pct_above_low is not None:
            assert r.pct_above_low >= 0.0


async def test_bid_calibration_no_match(
    httpx_mock, db_session: AsyncSession,
):
    await _populate_via_pipeline(httpx_mock, db_session, _v1_fixtures(3))
    out = await get_bid_calibration(
        db_session,
        contractor_name_match="zzzzznotreal",
        tenant_id=CUSTOMER_TENANT_ID,
    )
    assert out == []


async def test_bid_calibration_case_insensitive(
    httpx_mock, db_session: AsyncSession,
):
    """LOWER-LIKE means CANNON, cannon, Cannon all match identically."""
    await _populate_via_pipeline(httpx_mock, db_session, _v1_fixtures(5))

    upper = await get_bid_calibration(
        db_session, contractor_name_match="STAKER",
        tenant_id=CUSTOMER_TENANT_ID,
    )
    lower = await get_bid_calibration(
        db_session, contractor_name_match="staker",
        tenant_id=CUSTOMER_TENANT_ID,
    )
    mixed = await get_bid_calibration(
        db_session, contractor_name_match="Staker",
        tenant_id=CUSTOMER_TENANT_ID,
    )

    assert len(upper) == len(lower) == len(mixed)
    if upper:
        # Same per-quarter aggregates regardless of case.
        for u, low_, m in zip(upper, lower, mixed):
            assert u.quarter == low_.quarter == m.quarter
            assert u.bids_submitted == low_.bids_submitted == m.bids_submitted


# ---------------------------------------------------------------------------
# Tenant union: data lives under shared sentinel, customer tenant sees it

async def test_tenant_union_customer_sees_shared_network_data(
    httpx_mock, db_session: AsyncSession,
):
    """The cross-tenant read pattern: pipeline writes to
    SHARED_NETWORK_TENANT_ID; a customer tenant calling the service
    sees the data via the WHERE tenant_id IN (...) union."""
    await _populate_via_pipeline(httpx_mock, db_session, _v1_fixtures(3))

    # Customer tenant's own bid_events table is empty — they have NO
    # rows under their tenant_id. But the service should still return
    # data from SHARED_NETWORK_TENANT_ID via the union.
    curves = await get_competitor_curves(
        db_session,
        states=["ID"],
        months_back=240,
        min_bids=1,
        tenant_id=CUSTOMER_TENANT_ID,
    )
    gaps = await get_opportunity_gaps(
        db_session,
        bid_min=0,
        bid_max=10**9,
        months_back=240,
        tenant_id=CUSTOMER_TENANT_ID,
    )
    cal = await get_bid_calibration(
        db_session,
        contractor_name_match="staker",
        tenant_id=CUSTOMER_TENANT_ID,
    )

    assert len(curves) > 0, "customer tenant must see shared-network curves"
    assert len(gaps) > 0, "customer tenant must see shared-network gaps"
    assert len(cal) > 0, "customer tenant must see shared-network calibration"
