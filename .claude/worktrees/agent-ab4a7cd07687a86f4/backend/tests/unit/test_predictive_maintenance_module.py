"""Tests for app.modules.predictive_maintenance.

Strategy mirrors the per-module suites:
  1. Build a fresh SQLite DB per test via fixtures.
  2. ``Base.metadata.create_all`` builds the schema for ``tenants``,
     ``mart_predictive_maintenance``,
     ``mart_predictive_maintenance_history`` and ``mart_work_orders``
     (the tables are imported via ``app.services.excel_marts``).
  3. Seed a representative cross-tier / cross-status / cross-source
     mix, plus an out-of-tenant row to verify isolation.
  4. Drive HTTP through ``TestClient`` with dependency overrides so
     reads + mutations both flow through the real router.

The empty-database case is also covered explicitly — Phase 1 ships with
zero rows, so every endpoint must still return a valid 200.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.tenant import SubscriptionTier, Tenant, TenantStatus
# Importing this triggers Table registration on Base.metadata so
# create_all() picks the predictive_maintenance + work_orders tables up.
import app.services.excel_marts  # noqa: F401
from app.modules.predictive_maintenance.router import (
    _default_engine,
    get_engine,
    get_tenant_id,
    router as pm_router,
)
from app.modules.predictive_maintenance.schema import (
    FailureMode,
    MaintSource,
    MaintStatus,
    RiskTier,
)
from app.modules.predictive_maintenance.service import (
    AGE_FRESH_DAYS,
    AGE_MATURE_DAYS,
    get_detail,
    get_insights,
    get_summary,
    insert_prediction,
    list_predictions,
    acknowledge,
    complete,
    dismiss,
    schedule,
)


# Pinned at import time so the seed stays deterministic within a run.
NOW = datetime.now(timezone.utc).replace(microsecond=0)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


def _make_tenants(engine: Engine) -> tuple[str, str]:
    """Insert vancon + other-co tenants. Return their ids."""
    tenant_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    with sessionmaker(engine)() as s:
        s.add(
            Tenant(
                id=tenant_id,
                slug="vancon",
                company_name="VanCon Inc.",
                contact_email="admin@vancon.test",
                tier=SubscriptionTier.INTERNAL,
                status=TenantStatus.ACTIVE,
            )
        )
        s.add(
            Tenant(
                id=other_id,
                slug="other-co",
                company_name="OtherCo",
                contact_email="admin@other.test",
                tier=SubscriptionTier.STARTER,
                status=TenantStatus.ACTIVE,
            )
        )
        s.commit()
    return tenant_id, other_id


@pytest.fixture
def empty_engine(tmp_path) -> Engine:
    """Fresh SQLite + tenant rows, but no predictions."""
    url = f"sqlite:///{tmp_path / 'pm_empty.db'}"
    engine = create_engine(url, future=True)
    Base.metadata.create_all(engine)
    _make_tenants(engine)
    return engine


@pytest.fixture
def empty_tenant_id(empty_engine: Engine) -> str:
    with empty_engine.connect() as conn:
        return conn.execute(
            text("SELECT id FROM tenants WHERE slug = 'vancon'")
        ).scalar_one()


@pytest.fixture
def seeded_engine(tmp_path) -> Engine:
    """SQLite file with a representative seed across status, risk, source.

    Seeded rows under ``vancon``:

      1. EX-001 — critical, OPEN, failure_prediction, engine, $40k,
         predicted to fail in 5 days. Fresh (1 day old).
      2. EX-002 — high, OPEN, pm_overdue, hydraulic, $5k, due 10 days
         AGO (overdue). Mature (15 days old).
      3. EX-003 — medium, ACKNOWLEDGED, failure_prediction, electrical,
         $3k, predicted in 30 days. Stale (45 days old).
      4. EX-004 — low, SCHEDULED, pm_overdue, drivetrain, $1k, due in
         20 days, scheduled_for in 12 days. Mature (10 days old).
      5. EX-005 — high, COMPLETED, failure_prediction, engine, $20k.
         Resolved 2 days ago.
      6. EX-006 — medium, DISMISSED, pm_overdue, structural, $500.
         Dismissed 4 days ago.

    Plus one row under ``other-co`` (must not leak into vancon reads).

    Plus one work order under ``mart_work_orders`` for EX-001 so the
    detail endpoint can surface a ``recent_work_orders`` entry.
    """
    url = f"sqlite:///{tmp_path / 'pm_seeded.db'}"
    engine = create_engine(url, future=True)
    Base.metadata.create_all(engine)

    tenant_id, other_id = _make_tenants(engine)

    # Row 1: critical OPEN failure prediction, fresh, $40k engine.
    insert_prediction(
        engine, tenant_id,
        equipment_id="EX-001",
        equipment_label="EX-001 Cat 336 Excavator",
        risk_tier=RiskTier.CRITICAL,
        status=MaintStatus.OPEN,
        source=MaintSource.FAILURE_PREDICTION,
        failure_mode=FailureMode.ENGINE,
        recommended_action="Replace engine oil pump within 5 days.",
        description="Oil pressure trending down across last 6 WOs.",
        estimated_repair_cost=40000.0,
        estimated_downtime_hours=24.0,
        predicted_failure_date=NOW + timedelta(days=5),
        created_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(days=1),
        evidence=[
            {"label": "Last oil sample", "value": "12 ppm Fe",
             "link": None},
        ],
    )
    # Row 2: high OPEN pm_overdue (overdue 10 days), mature, $5k.
    insert_prediction(
        engine, tenant_id,
        equipment_id="EX-002",
        equipment_label="EX-002 Cat 320 Excavator",
        risk_tier=RiskTier.HIGH,
        status=MaintStatus.OPEN,
        source=MaintSource.PM_OVERDUE,
        failure_mode=FailureMode.HYDRAULIC,
        recommended_action="500-hr PM service overdue.",
        description="Calendar PM rolled past target date.",
        estimated_repair_cost=5000.0,
        estimated_downtime_hours=8.0,
        pm_due_date=NOW - timedelta(days=10),
        created_at=NOW - timedelta(days=15),
        updated_at=NOW - timedelta(days=15),
    )
    # Row 3: medium ACKNOWLEDGED failure_prediction, stale, $3k.
    insert_prediction(
        engine, tenant_id,
        equipment_id="EX-003",
        equipment_label="EX-003 Cat D6 Dozer",
        risk_tier=RiskTier.MEDIUM,
        status=MaintStatus.ACKNOWLEDGED,
        source=MaintSource.FAILURE_PREDICTION,
        failure_mode=FailureMode.ELECTRICAL,
        recommended_action="Inspect alternator harness.",
        description="Flagged after voltage drop pattern.",
        estimated_repair_cost=3000.0,
        estimated_downtime_hours=4.0,
        predicted_failure_date=NOW + timedelta(days=30),
        created_at=NOW - timedelta(days=45),
        updated_at=NOW - timedelta(days=2),
    )
    # Row 4: low SCHEDULED pm_overdue (future), $1k.
    insert_prediction(
        engine, tenant_id,
        equipment_id="EX-004",
        equipment_label="EX-004 Cat 950 Loader",
        risk_tier=RiskTier.LOW,
        status=MaintStatus.SCHEDULED,
        source=MaintSource.PM_OVERDUE,
        failure_mode=FailureMode.DRIVETRAIN,
        recommended_action="250-hr service due in 3 weeks.",
        estimated_repair_cost=1000.0,
        estimated_downtime_hours=2.0,
        pm_due_date=NOW + timedelta(days=20),
        scheduled_for=NOW + timedelta(days=12),
        created_at=NOW - timedelta(days=10),
        updated_at=NOW - timedelta(days=1),
    )
    # Row 5: high COMPLETED failure_prediction, resolved 2d ago.
    insert_prediction(
        engine, tenant_id,
        equipment_id="EX-005",
        equipment_label="EX-005 Cat 12M Grader",
        risk_tier=RiskTier.HIGH,
        status=MaintStatus.COMPLETED,
        source=MaintSource.FAILURE_PREDICTION,
        failure_mode=FailureMode.ENGINE,
        recommended_action="Replace coolant manifold.",
        estimated_repair_cost=20000.0,
        estimated_downtime_hours=12.0,
        predicted_failure_date=NOW - timedelta(days=2),
        created_at=NOW - timedelta(days=20),
        updated_at=NOW - timedelta(days=2),
    )
    # Row 6: medium DISMISSED pm_overdue.
    insert_prediction(
        engine, tenant_id,
        equipment_id="EX-006",
        equipment_label="EX-006 Compactor",
        risk_tier=RiskTier.MEDIUM,
        status=MaintStatus.DISMISSED,
        source=MaintSource.PM_OVERDUE,
        failure_mode=FailureMode.STRUCTURAL,
        recommended_action="False positive — unit retired.",
        estimated_repair_cost=500.0,
        estimated_downtime_hours=1.0,
        pm_due_date=NOW + timedelta(days=5),
        created_at=NOW - timedelta(days=8),
        updated_at=NOW - timedelta(days=4),
    )

    # Tenant-isolation guard — must never appear in vancon reads.
    insert_prediction(
        engine, other_id,
        equipment_id="OTHER-CANARY",
        equipment_label="OtherCo Canary Unit",
        risk_tier=RiskTier.CRITICAL,
        status=MaintStatus.OPEN,
        source=MaintSource.FAILURE_PREDICTION,
        failure_mode=FailureMode.OTHER,
        recommended_action="Should not leak across tenants.",
        estimated_repair_cost=99999.0,
        estimated_downtime_hours=99.0,
        predicted_failure_date=NOW + timedelta(days=1),
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW - timedelta(hours=1),
    )

    # One closed work order for EX-001 so detail.recent_work_orders has
    # something to project.
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO mart_work_orders
                    (tenant_id, work_order, equipment, description,
                     closed_date, total_cost)
                VALUES
                    (:t, 'WO-9001', 'EX-001', 'Coolant flush',
                     :closed, 1234.56)
                """
            ),
            {"t": tenant_id, "closed": NOW - timedelta(days=7)},
        )
    return engine


@pytest.fixture
def seeded_tenant_id(seeded_engine: Engine) -> str:
    with seeded_engine.connect() as conn:
        return conn.execute(
            text("SELECT id FROM tenants WHERE slug = 'vancon'")
        ).scalar_one()


@pytest.fixture
def open_prediction_id(seeded_engine: Engine, seeded_tenant_id: str) -> str:
    """Convenience — id of EX-001 (open, mutable)."""
    with seeded_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT id FROM mart_predictive_maintenance "
                "WHERE tenant_id = :t AND equipment_id = 'EX-001'"
            ),
            {"t": seeded_tenant_id},
        ).scalar_one()


@pytest.fixture
def completed_prediction_id(
    seeded_engine: Engine, seeded_tenant_id: str,
) -> str:
    """Id of EX-005 (terminal status — must reject mutations)."""
    with seeded_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT id FROM mart_predictive_maintenance "
                "WHERE tenant_id = :t AND equipment_id = 'EX-005'"
            ),
            {"t": seeded_tenant_id},
        ).scalar_one()


@pytest.fixture
def client(seeded_engine: Engine, seeded_tenant_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(pm_router, prefix="/api/predictive-maintenance")
    app.dependency_overrides[get_engine] = lambda: seeded_engine
    app.dependency_overrides[get_tenant_id] = lambda: seeded_tenant_id
    _default_engine.cache_clear()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def empty_client(empty_engine: Engine, empty_tenant_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(pm_router, prefix="/api/predictive-maintenance")
    app.dependency_overrides[get_engine] = lambda: empty_engine
    app.dependency_overrides[get_tenant_id] = lambda: empty_tenant_id
    _default_engine.cache_clear()
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# Empty-table tests — Phase 1 deployed state.                                 #
# --------------------------------------------------------------------------- #


class TestEmptyTable:
    """Every endpoint must return a valid 200 against zero rows."""

    def test_summary_zeros(self, empty_engine, empty_tenant_id):
        s = get_summary(empty_engine, empty_tenant_id)
        assert s.total_predictions == 0
        assert s.open_count == 0
        assert s.open_overdue_count == 0
        assert s.total_estimated_exposure == 0
        assert s.average_age_days is None
        assert s.oldest_open_age_days is None
        assert s.distinct_equipment == 0

    def test_list_empty(self, empty_engine, empty_tenant_id):
        r = list_predictions(empty_engine, empty_tenant_id)
        assert r.total == 0
        assert r.items == []

    def test_insights_empty(self, empty_engine, empty_tenant_id):
        ins = get_insights(empty_engine, empty_tenant_id)
        assert ins.risk_tier_breakdown.critical == 0
        assert ins.aging_breakdown.fresh == 0
        assert ins.top_equipment_exposure == []
        assert ins.failure_mode_impact == []
        assert ins.top_by_exposure == []
        assert ins.recent_completions == []

    def test_summary_endpoint_200(self, empty_client):
        r = empty_client.get("/api/predictive-maintenance/summary")
        assert r.status_code == 200
        assert r.json()["total_predictions"] == 0

    def test_list_endpoint_200(self, empty_client):
        r = empty_client.get("/api/predictive-maintenance/list")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 0
        assert body["items"] == []

    def test_insights_endpoint_200(self, empty_client):
        r = empty_client.get("/api/predictive-maintenance/insights")
        assert r.status_code == 200
        assert r.json()["risk_tier_breakdown"]["critical"] == 0


# --------------------------------------------------------------------------- #
# Service-level tests on the seeded data                                      #
# --------------------------------------------------------------------------- #


class TestGetSummary:
    def test_total_count(self, seeded_engine, seeded_tenant_id):
        # 6 vancon rows; OtherCo row excluded.
        s = get_summary(seeded_engine, seeded_tenant_id)
        assert s.total_predictions == 6

    def test_status_buckets(self, seeded_engine, seeded_tenant_id):
        s = get_summary(seeded_engine, seeded_tenant_id)
        assert s.open_count == 2  # EX-001, EX-002
        assert s.acknowledged_count == 1  # EX-003
        assert s.scheduled_count == 1  # EX-004
        assert s.completed_count == 1  # EX-005
        assert s.dismissed_count == 1  # EX-006

    def test_lifetime_risk_buckets(self, seeded_engine, seeded_tenant_id):
        s = get_summary(seeded_engine, seeded_tenant_id)
        assert s.critical_count == 1   # EX-001
        assert s.high_count == 2       # EX-002 (open) + EX-005 (completed)
        assert s.medium_count == 2     # EX-003 + EX-006
        assert s.low_count == 1        # EX-004

    def test_open_critical_and_overdue(
        self, seeded_engine, seeded_tenant_id,
    ):
        s = get_summary(seeded_engine, seeded_tenant_id)
        assert s.open_critical_count == 1  # EX-001
        # EX-002 pm_due_date is 10d ago -> overdue. EX-001 is in the
        # future so it is open but NOT overdue.
        assert s.open_overdue_count == 1

    def test_open_source_breakdown(self, seeded_engine, seeded_tenant_id):
        s = get_summary(seeded_engine, seeded_tenant_id)
        # Only EX-001 (failure_pred) and EX-002 (pm_overdue) are open.
        assert s.failure_prediction_count == 1
        assert s.pm_overdue_count == 1

    def test_open_exposure_totals(self, seeded_engine, seeded_tenant_id):
        s = get_summary(seeded_engine, seeded_tenant_id)
        # 40000 + 5000 = 45000 across the two open rows.
        assert s.total_estimated_exposure == 45000.0
        # 24 + 8 = 32 hours.
        assert s.total_estimated_downtime_hours == 32.0

    def test_age_stats(self, seeded_engine, seeded_tenant_id):
        s = get_summary(seeded_engine, seeded_tenant_id)
        # Open ages: 1 (EX-001) and 15 (EX-002). avg 8.0, max 15.
        assert s.average_age_days == 8.0
        assert s.oldest_open_age_days == 15

    def test_distinct_counts(self, seeded_engine, seeded_tenant_id):
        s = get_summary(seeded_engine, seeded_tenant_id)
        # 6 distinct equipment ids; 6 distinct failure modes used
        # (engine, hydraulic, electrical, drivetrain — and engine again
        # — plus structural). Engine appears twice -> 5 modes used.
        assert s.distinct_equipment == 6
        assert s.distinct_failure_modes == 5


class TestListPredictions:
    def test_default_returns_all_six(
        self, seeded_engine, seeded_tenant_id,
    ):
        r = list_predictions(seeded_engine, seeded_tenant_id)
        assert r.total == 6
        assert len(r.items) == 6

    def test_filter_status_open(self, seeded_engine, seeded_tenant_id):
        r = list_predictions(
            seeded_engine, seeded_tenant_id, status=MaintStatus.OPEN,
        )
        assert r.total == 2
        assert {row.equipment_id for row in r.items} == {"EX-001", "EX-002"}

    def test_filter_risk_critical(self, seeded_engine, seeded_tenant_id):
        r = list_predictions(
            seeded_engine, seeded_tenant_id, risk_tier=RiskTier.CRITICAL,
        )
        assert r.total == 1
        assert r.items[0].equipment_id == "EX-001"

    def test_filter_source_failure_prediction(
        self, seeded_engine, seeded_tenant_id,
    ):
        r = list_predictions(
            seeded_engine, seeded_tenant_id,
            source=MaintSource.FAILURE_PREDICTION,
        )
        # EX-001, EX-003, EX-005
        assert r.total == 3

    def test_filter_failure_mode_engine(
        self, seeded_engine, seeded_tenant_id,
    ):
        r = list_predictions(
            seeded_engine, seeded_tenant_id,
            failure_mode=FailureMode.ENGINE,
        )
        # EX-001 + EX-005
        assert r.total == 2

    def test_filter_overdue_only(self, seeded_engine, seeded_tenant_id):
        r = list_predictions(
            seeded_engine, seeded_tenant_id, overdue_only=True,
        )
        # Two rows have days_until_due < 0: EX-002 (open, pm 10d ago)
        # and EX-005 (completed, predicted_failure_date 2d ago). The
        # ``overdue_only`` filter doesn't narrow on status — it's a
        # pure date-arithmetic filter, matching the TS contract.
        assert r.total == 2
        assert {row.equipment_id for row in r.items} == {"EX-002", "EX-005"}
        for row in r.items:
            assert row.days_until_due is not None
            assert row.days_until_due < 0

    def test_filter_overdue_only_combined_with_status(
        self, seeded_engine, seeded_tenant_id,
    ):
        # The page's "open + overdue" KPI uses status=open AND
        # overdue_only=true together. Confirm the combo narrows
        # correctly to just EX-002.
        r = list_predictions(
            seeded_engine, seeded_tenant_id,
            status=MaintStatus.OPEN, overdue_only=True,
        )
        assert r.total == 1
        assert r.items[0].equipment_id == "EX-002"

    def test_filter_min_cost(self, seeded_engine, seeded_tenant_id):
        r = list_predictions(
            seeded_engine, seeded_tenant_id, min_cost=10000.0,
        )
        # >= 10k: EX-001 (40k), EX-005 (20k)
        assert r.total == 2
        assert {row.equipment_id for row in r.items} == {"EX-001", "EX-005"}

    def test_search(self, seeded_engine, seeded_tenant_id):
        r = list_predictions(
            seeded_engine, seeded_tenant_id, search="grader",
        )
        # Only EX-005 has "Grader" in the label.
        assert r.total == 1
        assert r.items[0].equipment_id == "EX-005"

    def test_filter_equipment_id(self, seeded_engine, seeded_tenant_id):
        r = list_predictions(
            seeded_engine, seeded_tenant_id, equipment_id="EX-002",
        )
        assert r.total == 1
        assert r.items[0].equipment_id == "EX-002"

    def test_sort_by_cost_desc(self, seeded_engine, seeded_tenant_id):
        r = list_predictions(
            seeded_engine, seeded_tenant_id,
            sort_by="estimated_repair_cost", sort_dir="desc",
        )
        costs = [row.estimated_repair_cost or 0 for row in r.items]
        assert costs == sorted(costs, reverse=True)

    def test_sort_by_risk_desc_puts_critical_first(
        self, seeded_engine, seeded_tenant_id,
    ):
        r = list_predictions(
            seeded_engine, seeded_tenant_id,
            sort_by="risk_tier", sort_dir="desc",
        )
        assert r.items[0].risk_tier is RiskTier.CRITICAL

    def test_pagination(self, seeded_engine, seeded_tenant_id):
        page1 = list_predictions(
            seeded_engine, seeded_tenant_id, page=1, page_size=4,
        )
        page2 = list_predictions(
            seeded_engine, seeded_tenant_id, page=2, page_size=4,
        )
        assert page1.total == 6
        assert len(page1.items) == 4
        assert len(page2.items) == 2
        ids1 = {row.id for row in page1.items}
        ids2 = {row.id for row in page2.items}
        assert ids1.isdisjoint(ids2)

    def test_age_days_computed(self, seeded_engine, seeded_tenant_id):
        r = list_predictions(
            seeded_engine, seeded_tenant_id,
            equipment_id="EX-003",
        )
        # EX-003 created 45 days ago -> age_days should be ~45.
        assert r.items[0].age_days >= 44

    def test_days_until_due_negative_when_overdue(
        self, seeded_engine, seeded_tenant_id,
    ):
        r = list_predictions(
            seeded_engine, seeded_tenant_id, equipment_id="EX-002",
        )
        # 10 days overdue -> -10 (give or take 1 for boundary precision).
        assert r.items[0].days_until_due is not None
        assert r.items[0].days_until_due <= -9

    def test_tenant_isolation(self, seeded_engine, seeded_tenant_id):
        r = list_predictions(seeded_engine, seeded_tenant_id)
        assert all(
            row.equipment_id != "OTHER-CANARY" for row in r.items
        )


class TestInsights:
    def test_risk_breakdown(self, seeded_engine, seeded_tenant_id):
        ins = get_insights(seeded_engine, seeded_tenant_id)
        assert ins.risk_tier_breakdown.critical == 1
        assert ins.risk_tier_breakdown.high == 2
        assert ins.risk_tier_breakdown.medium == 2
        assert ins.risk_tier_breakdown.low == 1

    def test_status_breakdown(self, seeded_engine, seeded_tenant_id):
        ins = get_insights(seeded_engine, seeded_tenant_id)
        assert ins.status_breakdown.open == 2
        assert ins.status_breakdown.acknowledged == 1
        assert ins.status_breakdown.scheduled == 1
        assert ins.status_breakdown.completed == 1
        assert ins.status_breakdown.dismissed == 1

    def test_failure_mode_breakdown(self, seeded_engine, seeded_tenant_id):
        ins = get_insights(seeded_engine, seeded_tenant_id)
        # engine appears in EX-001 + EX-005 -> 2
        assert ins.failure_mode_breakdown.engine == 2
        assert ins.failure_mode_breakdown.hydraulic == 1
        assert ins.failure_mode_breakdown.electrical == 1
        assert ins.failure_mode_breakdown.drivetrain == 1
        assert ins.failure_mode_breakdown.structural == 1
        assert ins.failure_mode_breakdown.other == 0

    def test_aging_buckets_open_only(
        self, seeded_engine, seeded_tenant_id,
    ):
        ins = get_insights(seeded_engine, seeded_tenant_id)
        # Open rows: EX-001 (1d -> fresh), EX-002 (15d -> mature).
        assert ins.aging_breakdown.fresh == 1
        assert ins.aging_breakdown.mature == 1
        assert ins.aging_breakdown.stale == 0

    def test_top_equipment_exposure_sorted_by_cost(
        self, seeded_engine, seeded_tenant_id,
    ):
        ins = get_insights(seeded_engine, seeded_tenant_id)
        # Top of the list is EX-001 ($40k) > EX-002 ($5k).
        assert ins.top_equipment_exposure[0].equipment_id == "EX-001"
        costs = [
            row.total_estimated_repair_cost
            for row in ins.top_equipment_exposure
        ]
        assert costs == sorted(costs, reverse=True)

    def test_failure_mode_impact_open_only(
        self, seeded_engine, seeded_tenant_id,
    ):
        ins = get_insights(seeded_engine, seeded_tenant_id)
        # Open rows are engine (40k) and hydraulic (5k). Other modes
        # have closed rows but are excluded from the open rollup.
        modes = {
            row.failure_mode: row.total_estimated_repair_cost
            for row in ins.failure_mode_impact
        }
        assert modes.get(FailureMode.ENGINE) == 40000.0
        assert modes.get(FailureMode.HYDRAULIC) == 5000.0
        assert FailureMode.ELECTRICAL not in modes  # closed row, excluded

    def test_top_by_exposure_open_only(
        self, seeded_engine, seeded_tenant_id,
    ):
        ins = get_insights(seeded_engine, seeded_tenant_id)
        # Only open rows -> 2 entries.
        assert len(ins.top_by_exposure) == 2
        assert ins.top_by_exposure[0].equipment_label.startswith("EX-001")

    def test_recent_completions_terminal_only(
        self, seeded_engine, seeded_tenant_id,
    ):
        ins = get_insights(seeded_engine, seeded_tenant_id)
        # EX-005 (completed) + EX-006 (dismissed).
        assert len(ins.recent_completions) == 2
        statuses = {row.status for row in ins.recent_completions}
        assert statuses == {MaintStatus.COMPLETED, MaintStatus.DISMISSED}


class TestDetail:
    def test_basic_payload(
        self, seeded_engine, seeded_tenant_id, open_prediction_id,
    ):
        d = get_detail(seeded_engine, seeded_tenant_id, open_prediction_id)
        assert d.id == open_prediction_id
        assert d.equipment_id == "EX-001"
        assert d.risk_tier is RiskTier.CRITICAL
        assert d.status is MaintStatus.OPEN
        assert d.estimated_repair_cost == 40000.0
        assert d.days_until_due is not None
        assert d.days_until_due > 0

    def test_evidence_parsed(
        self, seeded_engine, seeded_tenant_id, open_prediction_id,
    ):
        d = get_detail(seeded_engine, seeded_tenant_id, open_prediction_id)
        assert len(d.evidence) == 1
        assert d.evidence[0].label == "Last oil sample"
        assert d.evidence[0].value == "12 ppm Fe"

    def test_recent_work_orders_joined(
        self, seeded_engine, seeded_tenant_id, open_prediction_id,
    ):
        d = get_detail(seeded_engine, seeded_tenant_id, open_prediction_id)
        # WO-9001 was seeded against EX-001.
        assert len(d.recent_work_orders) == 1
        wo = d.recent_work_orders[0]
        assert wo.wo_number == "WO-9001"
        assert wo.cost == 1234.56

    def test_history_empty_initially(
        self, seeded_engine, seeded_tenant_id, open_prediction_id,
    ):
        d = get_detail(seeded_engine, seeded_tenant_id, open_prediction_id)
        # Insert helper doesn't write history rows, so it starts empty.
        assert d.history == []

    def test_404_on_unknown_id(self, seeded_engine, seeded_tenant_id):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            get_detail(seeded_engine, seeded_tenant_id, "no-such-id")
        assert exc.value.status_code == 404


# --------------------------------------------------------------------------- #
# Mutation tests                                                              #
# --------------------------------------------------------------------------- #


class TestMutations:
    def test_acknowledge_changes_status(
        self, seeded_engine, seeded_tenant_id, open_prediction_id,
    ):
        d = acknowledge(
            seeded_engine, seeded_tenant_id, open_prediction_id,
            note="Triaged by mechanic",
        )
        assert d.status is MaintStatus.ACKNOWLEDGED
        assert len(d.history) == 1
        assert d.history[0].status is MaintStatus.ACKNOWLEDGED
        assert d.history[0].note == "Triaged by mechanic"

    def test_schedule_sets_scheduled_for(
        self, seeded_engine, seeded_tenant_id, open_prediction_id,
    ):
        when = NOW + timedelta(days=7)
        d = schedule(
            seeded_engine, seeded_tenant_id, open_prediction_id,
            scheduled_for=when, note="Booked into Tue slot",
        )
        assert d.status is MaintStatus.SCHEDULED
        assert d.scheduled_for is not None
        # SQLite roundtrip drops timezone — just check the date matches.
        assert d.scheduled_for.date() == when.date()

    def test_complete_is_terminal(
        self, seeded_engine, seeded_tenant_id, open_prediction_id,
    ):
        d = complete(
            seeded_engine, seeded_tenant_id, open_prediction_id,
            completed_at=None, note="Repair done",
        )
        assert d.status is MaintStatus.COMPLETED
        # A subsequent mutation must be rejected with 409.
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            acknowledge(
                seeded_engine, seeded_tenant_id, open_prediction_id,
                note="should fail",
            )
        assert exc.value.status_code == 409

    def test_dismiss_records_reason(
        self, seeded_engine, seeded_tenant_id, open_prediction_id,
    ):
        d = dismiss(
            seeded_engine, seeded_tenant_id, open_prediction_id,
            reason="Sensor false positive",
        )
        assert d.status is MaintStatus.DISMISSED
        assert d.history[-1].note == "Sensor false positive"

    def test_terminal_row_rejects_mutation(
        self, seeded_engine, seeded_tenant_id, completed_prediction_id,
    ):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            acknowledge(
                seeded_engine, seeded_tenant_id, completed_prediction_id,
                note="should fail",
            )
        assert exc.value.status_code == 409

    def test_404_on_unknown_id(self, seeded_engine, seeded_tenant_id):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            acknowledge(
                seeded_engine, seeded_tenant_id, "no-such-id", note=None,
            )
        assert exc.value.status_code == 404


# --------------------------------------------------------------------------- #
# HTTP-level tests                                                            #
# --------------------------------------------------------------------------- #


class TestHTTP:
    def test_summary_endpoint(self, client):
        r = client.get("/api/predictive-maintenance/summary")
        assert r.status_code == 200
        body = r.json()
        assert body["total_predictions"] == 6
        assert body["open_count"] == 2
        assert body["open_overdue_count"] == 1

    def test_list_endpoint_pagination(self, client):
        r = client.get(
            "/api/predictive-maintenance/list",
            params={"page": 1, "page_size": 3},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 6
        assert len(body["items"]) == 3

    def test_list_filter(self, client):
        r = client.get(
            "/api/predictive-maintenance/list",
            params={"status": "open"},
        )
        body = r.json()
        assert body["total"] == 2
        equipment_ids = {row["equipment_id"] for row in body["items"]}
        assert equipment_ids == {"EX-001", "EX-002"}

    def test_insights_endpoint(self, client):
        r = client.get("/api/predictive-maintenance/insights")
        assert r.status_code == 200
        body = r.json()
        assert body["risk_tier_breakdown"]["critical"] == 1
        assert len(body["recent_completions"]) == 2

    def test_detail_endpoint(self, client, open_prediction_id):
        r = client.get(
            f"/api/predictive-maintenance/{open_prediction_id}",
        )
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == open_prediction_id
        assert body["recent_work_orders"][0]["wo_number"] == "WO-9001"

    def test_detail_404(self, client):
        r = client.get("/api/predictive-maintenance/no-such-id")
        assert r.status_code == 404

    def test_acknowledge_endpoint(self, client, open_prediction_id):
        r = client.post(
            f"/api/predictive-maintenance/{open_prediction_id}/acknowledge",
            json={"note": "via http"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "acknowledged"

    def test_schedule_endpoint(self, client, open_prediction_id):
        when = (NOW + timedelta(days=3)).isoformat()
        r = client.post(
            f"/api/predictive-maintenance/{open_prediction_id}/schedule",
            json={"scheduled_for": when, "note": "Tue"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "scheduled"
        assert body["scheduled_for"] is not None

    def test_schedule_requires_scheduled_for(
        self, client, open_prediction_id,
    ):
        r = client.post(
            f"/api/predictive-maintenance/{open_prediction_id}/schedule",
            json={},
        )
        assert r.status_code == 422

    def test_complete_endpoint(self, client, open_prediction_id):
        r = client.post(
            f"/api/predictive-maintenance/{open_prediction_id}/complete",
            json={},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

    def test_dismiss_endpoint(self, client, open_prediction_id):
        r = client.post(
            f"/api/predictive-maintenance/{open_prediction_id}/dismiss",
            json={"reason": "false alarm"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "dismissed"
        assert r.json()["history"][-1]["note"] == "false alarm"

    def test_terminal_row_409(self, client, completed_prediction_id):
        r = client.post(
            f"/api/predictive-maintenance/{completed_prediction_id}/acknowledge",
            json={},
        )
        assert r.status_code == 409


# Belt-and-suspenders sanity check on the AGE constants — protects future
# refactors from silently changing the bucket boundaries the UI legend
# documents.
def test_age_constants():
    assert AGE_FRESH_DAYS == 7
    assert AGE_MATURE_DAYS == 30
