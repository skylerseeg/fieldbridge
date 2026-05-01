"""Tests for the Layer A/B Market Intel schema additions (Phase 1).

What this locks in:

  * Every new model is importable and ``Base.metadata.create_all``
    succeeds against in-memory SQLite (the CI dialect — see
    ``.github/workflows/ci.yml``).
  * JSON columns round-trip Python ``list`` and ``dict`` values
    (the cross-dialect contract — JSON not ARRAY).
  * ``BidResult`` writes accept the new ``listed_subs`` /
    ``listed_suppliers`` / ``pct_above_low`` / ``is_disqualified``
    / ``bond_amount`` / ``pipeline_run_id`` fields.
  * ``BidBreakdown`` is the new Layer A foundation table — required
    columns are required, optional columns may be NULL, JSON
    cost_buckets round-trips.
  * ``PipelineRun`` accepts a counters dict and the FK from
    ``BidResult.pipeline_run_id`` resolves correctly.

Reference: ``docs/market-intel-data-state.md`` § 6.
"""
from __future__ import annotations

import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

# app.models.__init__ pulls from fieldbridge.saas.* — needs the repo
# root on sys.path. conftest.py already does this for tests/, but
# being explicit keeps this file independently runnable too.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.database import Base  # noqa: E402
from app.models.bid_breakdown import BidBreakdown  # noqa: E402
from app.models.bid_event import BidEvent  # noqa: E402
from app.models.bid_result import BidResult  # noqa: E402
from app.models.contractor import Contractor  # noqa: E402
from app.models.pipeline_run import PipelineRun  # noqa: E402
from app.models.tenant import (  # noqa: E402
    SubscriptionTier,
    Tenant,
    TenantStatus,
)


@pytest.fixture
def engine(tmp_path):
    """Sync SQLite engine — same dialect CI runs against, just sync
    so the test stays simple. ``create_all`` exercises the model
    DDL the migration script issues by hand."""
    eng = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    Session = sessionmaker(engine, expire_on_commit=False)
    with Session() as s:
        yield s


@pytest.fixture
def tenant_id(session) -> str:
    tid = str(uuid.uuid4())
    session.add(
        Tenant(
            id=tid,
            slug="layer-ab-test",
            company_name="Layer AB Test Inc.",
            contact_email="admin@test.example",
            tier=SubscriptionTier.INTERNAL,
            status=TenantStatus.ACTIVE,
        )
    )
    session.commit()
    return tid


# ---------------------------------------------------------------------------
# 1. Schema definitions — every model imports cleanly and create_all
#    succeeds against SQLite.

def test_create_all_succeeds(engine):
    """If this test fails, the model file has a typo or a Postgres-
    only column type. The fixture itself runs create_all; we just
    assert the engine still has connectivity afterward."""
    with engine.connect() as conn:
        result = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' "
            "ORDER BY name;"
        ).fetchall()
    table_names = {row[0] for row in result}
    # The new tables landed.
    assert "pipeline_runs" in table_names
    assert "bid_breakdowns" in table_names
    # Existing Market Intel tables still here.
    assert "bid_events" in table_names
    assert "bid_results" in table_names
    assert "contractors" in table_names


# ---------------------------------------------------------------------------
# 2. BidEvent — round-trip with new Layer A/B columns populated.

def test_bid_event_round_trip_with_new_columns(session, tenant_id):
    event = BidEvent(
        tenant_id=tenant_id,
        source_url="https://itd.idaho.gov/test/abstract.pdf",
        source_state="ID",
        source_network="state_dot_id",
        raw_html_hash="a" * 64,
        project_title="US-95 Overlay (Phase 1 schema test)",
        project_owner="ITD",
        work_scope="HMA overlay 12 miles",
        csi_codes=["3210", "3220"],
        # Layer A/B forward-compat columns
        job_type="paving",
        job_subtype="overlay",
        scope_keywords=["hma", "overlay", "12mi"],
        agency_type="state_dot",
        funding_source="iija",
        project_size_band="5M-25M",
        prevailing_wage=True,
        award_date=date(2026, 5, 15),
        engineer_estimate=8_500_000.00,
        bid_open_date=date(2026, 4, 1),
        bid_status="awarded",
        location_state="ID",
    )
    session.add(event)
    session.commit()

    fetched = session.scalar(select(BidEvent).where(BidEvent.id == event.id))
    assert fetched is not None
    assert fetched.job_type == "paving"
    assert fetched.job_subtype == "overlay"
    assert fetched.scope_keywords == ["hma", "overlay", "12mi"]
    assert fetched.agency_type == "state_dot"
    assert fetched.funding_source == "iija"
    assert fetched.project_size_band == "5M-25M"
    assert fetched.prevailing_wage is True
    assert fetched.award_date == date(2026, 5, 15)
    assert float(fetched.engineer_estimate) == 8_500_000.00
    # updated_at populated by server default
    assert fetched.updated_at is not None


def test_bid_event_prevailing_wage_tristate(session, tenant_id):
    """prevailing_wage is True / False / NULL — the NULL state is
    legitimate ('we don't know yet')."""
    e = BidEvent(
        tenant_id=tenant_id,
        source_url="https://itd.idaho.gov/test/x.pdf",
        source_state="ID",
        source_network="state_dot_id",
        raw_html_hash="b" * 64,
        project_title="Prevailing wage NULL test",
    )
    session.add(e)
    session.commit()
    fetched = session.scalar(select(BidEvent).where(BidEvent.id == e.id))
    assert fetched.prevailing_wage is None


# ---------------------------------------------------------------------------
# 3. BidResult — round-trip with listed_subs / listed_suppliers JSON
#    columns plus the operational fields.

def test_bid_result_round_trip_with_new_columns(session, tenant_id):
    event = BidEvent(
        tenant_id=tenant_id,
        source_url="https://itd.idaho.gov/test/abstract2.pdf",
        source_state="ID",
        source_network="state_dot_id",
        raw_html_hash="c" * 64,
        project_title="Layer B test",
    )
    session.add(event)
    session.commit()

    result = BidResult(
        tenant_id=tenant_id,
        bid_event_id=event.id,
        contractor_name="Western Construction Inc.",
        bid_amount=8_400_000.00,
        rank=1,
        is_low_bidder=True,
        is_awarded=True,
        # Layer B forward-compat
        pct_above_low=0.0000,
        is_disqualified=False,
        bond_amount=420_000.00,
        listed_subs=[
            {
                "name": "Mountain Striping LLC",
                "scope": "pavement marking",
                "amount": 175_000.00,
                "csi_code": "3217",
                "used": True,
            },
        ],
        listed_suppliers=[
            {
                "name": "Boise Aggregate",
                "material": "3/4 minus base",
                "amount": 90_000.00,
                "csi_code": "3105",
                "used": True,
            },
        ],
    )
    session.add(result)
    session.commit()

    fetched = session.scalar(
        select(BidResult).where(BidResult.id == result.id)
    )
    assert fetched is not None
    assert fetched.is_disqualified is False
    assert float(fetched.bond_amount) == 420_000.00
    assert len(fetched.listed_subs) == 1
    assert fetched.listed_subs[0]["name"] == "Mountain Striping LLC"
    assert fetched.listed_subs[0]["used"] is True
    assert len(fetched.listed_suppliers) == 1
    assert fetched.listed_suppliers[0]["material"] == "3/4 minus base"
    # Server-defaulted timestamps
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


def test_bid_result_is_disqualified_defaults_false(session, tenant_id):
    """``is_disqualified`` should default to False without the caller
    supplying it — the server_default and Python default agree."""
    event = BidEvent(
        tenant_id=tenant_id,
        source_url="https://itd.idaho.gov/test/abstract3.pdf",
        source_state="ID",
        source_network="state_dot_id",
        raw_html_hash="d" * 64,
        project_title="Disqualified default test",
    )
    session.add(event)
    session.commit()

    result = BidResult(
        tenant_id=tenant_id,
        bid_event_id=event.id,
        contractor_name="Default Test Co.",
        bid_amount=1_000_000.00,
    )
    session.add(result)
    session.commit()

    fetched = session.scalar(
        select(BidResult).where(BidResult.id == result.id)
    )
    assert fetched.is_disqualified is False


# ---------------------------------------------------------------------------
# 4. BidBreakdown — Layer A foundation. JSON cost_buckets round-trip.

def test_bid_breakdown_round_trip(session, tenant_id):
    breakdown = BidBreakdown(
        tenant_id=tenant_id,
        vista_estimate_id="HCSS-2026-04-001",
        submitted_amount=8_400_000.00,
        estimate_date=date(2026, 3, 28),
        cost_buckets={
            "labor": 1_200_000.00,
            "materials": 3_500_000.00,
            "equipment": 1_800_000.00,
            "subs": 1_400_000.00,
            "overhead": 500_000.00,
        },
        man_hours=12_400.00,
        crew_composition={"operators": 6, "laborers": 8, "foreman": 2},
        equipment_mix={"dozer_d6": 200, "excavator_320": 80},
        sub_quotes=[
            {
                "sub": "Mountain Striping LLC",
                "scope": "pavement marking",
                "amount": 175_000.00,
                "used": True,
                "csi_code": "3217",
            },
        ],
        supplier_quotes=[
            {
                "supplier": "Boise Aggregate",
                "material": "3/4 minus base",
                "amount": 90_000.00,
                "used": True,
                "csi_code": "3105",
            },
        ],
        won=True,
        notes="Won by 0.7%",
    )
    session.add(breakdown)
    session.commit()

    fetched = session.scalar(
        select(BidBreakdown).where(BidBreakdown.id == breakdown.id)
    )
    assert fetched is not None
    assert fetched.cost_buckets["labor"] == 1_200_000.00
    assert fetched.cost_buckets["overhead"] == 500_000.00
    assert fetched.crew_composition["operators"] == 6
    assert fetched.equipment_mix["dozer_d6"] == 200
    assert len(fetched.sub_quotes) == 1
    assert fetched.sub_quotes[0]["used"] is True
    assert fetched.won is True
    assert float(fetched.man_hours) == 12_400.00


def test_bid_breakdown_optional_fields_null(session, tenant_id):
    """Required fields = id, tenant_id, submitted_amount, estimate_date,
    cost_buckets. Everything else may be NULL."""
    breakdown = BidBreakdown(
        tenant_id=tenant_id,
        submitted_amount=500_000.00,
        estimate_date=date(2026, 1, 15),
        cost_buckets={
            "labor": 100_000,
            "materials": 200_000,
            "equipment": 100_000,
            "subs": 50_000,
            "overhead": 50_000,
        },
    )
    session.add(breakdown)
    session.commit()

    fetched = session.scalar(
        select(BidBreakdown).where(BidBreakdown.id == breakdown.id)
    )
    assert fetched.bid_event_id is None
    assert fetched.vista_estimate_id is None
    assert fetched.man_hours is None
    assert fetched.crew_composition is None
    assert fetched.won is False  # server default


def test_bid_breakdown_vista_estimate_id_unique(session, tenant_id):
    """``vista_estimate_id`` is UNIQUE — an HCSS estimate maps to at
    most one breakdown row."""
    a = BidBreakdown(
        tenant_id=tenant_id,
        vista_estimate_id="HCSS-DUPE-1",
        submitted_amount=100.00,
        estimate_date=date(2026, 1, 1),
        cost_buckets={"labor": 100, "materials": 0, "equipment": 0,
                      "subs": 0, "overhead": 0},
    )
    session.add(a)
    session.commit()

    b = BidBreakdown(
        tenant_id=tenant_id,
        vista_estimate_id="HCSS-DUPE-1",  # collision
        submitted_amount=200.00,
        estimate_date=date(2026, 1, 2),
        cost_buckets={"labor": 200, "materials": 0, "equipment": 0,
                      "subs": 0, "overhead": 0},
    )
    session.add(b)
    with pytest.raises(Exception):  # IntegrityError on SQLite
        session.commit()
    session.rollback()


# ---------------------------------------------------------------------------
# 5. PipelineRun — counters JSON round-trip + FK from BidResult resolves.

def test_pipeline_run_round_trip(session, tenant_id):
    run = PipelineRun(
        tenant_id=tenant_id,
        pipeline_name="itd",
        status="ok",
        finished_at=datetime.now(timezone.utc),
        counters={
            "discovered": 12,
            "fetched": 12,
            "parsed": 11,
            "skipped_idempotent": 5,
            "wrote_events": 6,
            "wrote_results": 24,
        },
    )
    session.add(run)
    session.commit()

    fetched = session.scalar(
        select(PipelineRun).where(PipelineRun.id == run.id)
    )
    assert fetched is not None
    assert fetched.pipeline_name == "itd"
    assert fetched.status == "ok"
    assert fetched.counters["discovered"] == 12
    assert fetched.counters["wrote_events"] == 6
    assert fetched.started_at is not None  # server default


def test_pipeline_run_status_defaults_running(session, tenant_id):
    """``status`` defaults to 'running' for a freshly opened run."""
    run = PipelineRun(
        tenant_id=tenant_id,
        pipeline_name="excel_ingest",
    )
    session.add(run)
    session.commit()

    fetched = session.scalar(
        select(PipelineRun).where(PipelineRun.id == run.id)
    )
    assert fetched.status == "running"


def test_bid_result_pipeline_run_fk_resolves(session, tenant_id):
    """``bid_results.pipeline_run_id`` should reference a PipelineRun
    row when set."""
    run = PipelineRun(
        tenant_id=tenant_id,
        pipeline_name="itd",
        status="ok",
        counters={"wrote_events": 1},
    )
    session.add(run)
    session.commit()

    event = BidEvent(
        tenant_id=tenant_id,
        source_url="https://itd.idaho.gov/test/fk.pdf",
        source_state="ID",
        source_network="state_dot_id",
        raw_html_hash="e" * 64,
        project_title="FK resolution test",
        pipeline_run_id=run.id,
    )
    session.add(event)
    session.commit()

    result = BidResult(
        tenant_id=tenant_id,
        bid_event_id=event.id,
        contractor_name="FK Test Co.",
        bid_amount=1_500_000.00,
        pipeline_run_id=run.id,
    )
    session.add(result)
    session.commit()

    # Round-trip the result and confirm the FK column survived.
    fetched_result = session.scalar(
        select(BidResult).where(BidResult.id == result.id)
    )
    assert fetched_result.pipeline_run_id == run.id

    # And confirm we can resolve the run via the FK value.
    fetched_run = session.scalar(
        select(PipelineRun).where(PipelineRun.id == fetched_result.pipeline_run_id)
    )
    assert fetched_run is not None
    assert fetched_run.pipeline_name == "itd"


# ---------------------------------------------------------------------------
# 6. Contractor — created_at/updated_at server defaults populate.

def test_contractor_timestamps_populated(session, tenant_id):
    c = Contractor(
        tenant_id=tenant_id,
        canonical_name="Western Construction",
        name_variants=["Western Construction Inc.", "Western Construction"],
    )
    session.add(c)
    session.commit()

    fetched = session.scalar(
        select(Contractor).where(Contractor.id == c.id)
    )
    assert fetched.created_at is not None
    assert fetched.updated_at is not None
