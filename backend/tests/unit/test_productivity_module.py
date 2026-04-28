"""Tests for app.modules.productivity.

Strategy mirrors test_jobs_module.py:
  1. Fresh SQLite DB per test via the seeded_engine fixture.
  2. Register every mart Table against Base.metadata, create_all().
  3. Seed a canonical set of phases that hits every PhaseStatus path
     and every labor/equipment combination (labor-only, equip-only,
     both, neither/unknown).
  4. Drive the API through TestClient with dependency overrides.

Canonical seed (anchored to NOW so the as_of timestamp stays fresh):

  Job   Phase             Labor                   Equipment             Worst status
  -------------------------------------------------------------------------------
  J1    P_LABOR_ON        actual=40 est=100 50%   —                     ON_TRACK
  J1    P_OVER_BOTH       actual=180 est=100 80%  actual=120 est=100    OVER_BUDGET
  J1    P_BEHIND_LABOR    actual=50 est=100 20%   —                     BEHIND_PACE
  J1    P_DONE            actual=130 est=100 100% actual=110 est=100    COMPLETE
  J2    P_UNK_ZERO_EST    actual=10 est=0   30%   —                     UNKNOWN
  J2    P_EQUIP_ON        —                       actual=30 est=80 50%  ON_TRACK

Distinct jobs: 2. Phases: 6.  Status counts: 1 OVER, 1 BEHIND, 2 ON_TRACK,
1 COMPLETE, 1 UNKNOWN.
"""
from __future__ import annotations

import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import sessionmaker

# Register every mart Table against Base.metadata so create_all() picks
# up mart_productivity_labor + mart_productivity_equipment.
import app.services.excel_marts  # noqa: F401
import app.services.excel_marts.productivity  # noqa: F401
from app.core.database import Base
from app.models.tenant import SubscriptionTier, Tenant, TenantStatus
from app.modules.productivity.router import (
    _default_engine,
    get_engine,
    get_tenant_id,
    router as productivity_router,
)
from app.modules.productivity.schema import PhaseStatus
from app.modules.productivity.service import (
    _classify,
    _severity,
    _strip_key,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


NOW = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


@pytest.fixture
def seeded_engine(tmp_path) -> Engine:
    url = f"sqlite:///{tmp_path / 'productivity_test.db'}"
    engine = create_engine(url, future=True)
    Base.metadata.create_all(engine)

    tenant_id = str(uuid.uuid4())
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
        s.commit()

    end = NOW + timedelta(days=180)

    # Helper: build a row dict matching the productivity mart's columns.
    def _row(
        job_label: str,
        phase_label: str,
        actual: float | None,
        est: float | None,
        pct_complete: float | None,
        units: float = 0.0,
    ) -> dict:
        variance = (
            (est - actual) if (est is not None and actual is not None)
            else None
        )
        pct_used = (actual / est) if (est and actual is not None) else None
        return {
            "tenant_id": tenant_id,
            "job_label": job_label,
            "phase_label": phase_label,
            "actual_hours": actual,
            "est_hours": est,
            "variance_hours": variance,
            "percent_used": pct_used,
            "percent_complete": pct_complete,
            "units_complete": units,
            "actual_units": units,
            "budget_hours": (
                est * pct_complete
                if (est is not None and pct_complete is not None) else None
            ),
            "budget_minus_actual": None,
            "projected_hours_calc": None,
            "projected_hours_pm": None,
            "efficiency_rate": None,
            "_workbook_separator": None,
            "project_end_date": end,
        }

    labor_rows = [
        # J1
        _row(" J1", " P_LABOR_ON", 40.0, 100.0, 0.50),
        _row(" J1", " P_OVER_BOTH", 180.0, 100.0, 0.80),
        _row(" J1", " P_BEHIND_LABOR", 50.0, 100.0, 0.20),
        _row(" J1", " P_DONE", 130.0, 100.0, 1.00),
        # J2
        _row("J2", "P_UNK_ZERO_EST", 10.0, 0.0, 0.30),
    ]
    equipment_rows = [
        _row(" J1", " P_OVER_BOTH", 120.0, 100.0, 0.80),
        _row(" J1", " P_DONE", 110.0, 100.0, 1.00),
        _row("J2", "P_EQUIP_ON", 30.0, 80.0, 0.50),
    ]

    cols = (
        "tenant_id, job_label, phase_label, actual_hours, est_hours, "
        "variance_hours, percent_used, percent_complete, units_complete, "
        "actual_units, budget_hours, budget_minus_actual, "
        "projected_hours_calc, projected_hours_pm, efficiency_rate, "
        "_workbook_separator, project_end_date"
    )
    bind = (
        ":tenant_id, :job_label, :phase_label, :actual_hours, :est_hours, "
        ":variance_hours, :percent_used, :percent_complete, :units_complete, "
        ":actual_units, :budget_hours, :budget_minus_actual, "
        ":projected_hours_calc, :projected_hours_pm, :efficiency_rate, "
        ":_workbook_separator, :project_end_date"
    )

    with engine.begin() as conn:
        for r in labor_rows:
            conn.execute(
                text(f"INSERT INTO mart_productivity_labor ({cols}) "
                     f"VALUES ({bind})"),
                r,
            )
        for r in equipment_rows:
            conn.execute(
                text(f"INSERT INTO mart_productivity_equipment ({cols}) "
                     f"VALUES ({bind})"),
                r,
            )

    return engine


@pytest.fixture
def seeded_tenant_id(seeded_engine: Engine) -> str:
    with sessionmaker(seeded_engine)() as s:
        return s.execute(
            text("SELECT id FROM tenants WHERE slug = 'vancon'")
        ).scalar_one()


@pytest.fixture
def client(seeded_engine: Engine, seeded_tenant_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(productivity_router, prefix="/api/productivity")

    app.dependency_overrides[get_engine] = lambda: seeded_engine
    app.dependency_overrides[get_tenant_id] = lambda: seeded_tenant_id

    _default_engine.cache_clear()

    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# Pure helpers                                                                #
# --------------------------------------------------------------------------- #


class TestStripKey:
    def test_strips_leading(self):
        assert _strip_key(" J1") == "J1"

    def test_collapses_internal(self):
        assert _strip_key("  J  1  ") == "J 1"

    def test_none_is_empty(self):
        assert _strip_key(None) == ""


class TestClassify:
    def test_complete_when_pct_complete_at_one(self):
        status, pct_used, _ = _classify(
            actual=130.0, est=100.0, pct_complete=1.0, pace_band_pct=10.0,
        )
        assert status is PhaseStatus.COMPLETE
        # pct_used still computed for context
        assert pct_used == 1.30

    def test_unknown_when_zero_estimate(self):
        status, *_ = _classify(
            actual=10.0, est=0.0, pct_complete=0.5, pace_band_pct=10.0,
        )
        assert status is PhaseStatus.UNKNOWN

    def test_unknown_when_no_actual(self):
        status, *_ = _classify(
            actual=None, est=100.0, pct_complete=0.5, pace_band_pct=10.0,
        )
        assert status is PhaseStatus.UNKNOWN

    def test_over_budget_when_pct_used_above_one(self):
        status, pct_used, _ = _classify(
            actual=180.0, est=100.0, pct_complete=0.80, pace_band_pct=10.0,
        )
        assert status is PhaseStatus.OVER_BUDGET
        assert pct_used == 1.80

    def test_behind_pace_when_used_outpaces_complete(self):
        status, *_ = _classify(
            actual=50.0, est=100.0, pct_complete=0.20, pace_band_pct=10.0,
        )
        # pct_used 0.50 - pct_complete 0.20 = 0.30 > band 0.10
        assert status is PhaseStatus.BEHIND_PACE

    def test_on_track_inside_band(self):
        status, *_ = _classify(
            actual=40.0, est=100.0, pct_complete=0.50, pace_band_pct=10.0,
        )
        # pct_used 0.40 < pct_complete 0.50 -> ahead of pace, ON_TRACK
        assert status is PhaseStatus.ON_TRACK

    def test_on_track_when_no_pct_complete(self):
        status, *_ = _classify(
            actual=40.0, est=100.0, pct_complete=None, pace_band_pct=10.0,
        )
        assert status is PhaseStatus.ON_TRACK


class TestSeverity:
    def test_over_budget_returns_hours_over(self):
        assert _severity(
            PhaseStatus.OVER_BUDGET, actual=180.0, est=100.0, spi=None,
        ) == 80.0

    def test_behind_pace_returns_actual_times_one_minus_spi(self):
        assert _severity(
            PhaseStatus.BEHIND_PACE, actual=50.0, est=100.0, spi=0.4,
        ) == pytest.approx(30.0)

    def test_on_track_returns_zero(self):
        assert _severity(
            PhaseStatus.ON_TRACK, actual=40.0, est=100.0, spi=1.25,
        ) == 0.0


# --------------------------------------------------------------------------- #
# /summary                                                                    #
# --------------------------------------------------------------------------- #


class TestSummary:
    def test_totals(self, client):
        r = client.get("/api/productivity/summary")
        assert r.status_code == 200
        body = r.json()

        assert body["total_jobs"] == 2
        assert body["total_phases"] == 6

        # Labor: 5 phases. actual 40 + 180 + 50 + 130 + 10 = 410
        # est: 100 + 100 + 100 + 100 + 0 = 400
        assert body["labor_totals"]["phases"] == 5
        assert body["labor_totals"]["actual_hours"] == 410.0
        assert body["labor_totals"]["est_hours"] == 400.0
        assert body["labor_totals"]["percent_used"] == pytest.approx(
            410.0 / 400.0
        )

        # Equipment: 3 phases. actual 120 + 110 + 30 = 260; est 100+100+80 = 280
        assert body["equipment_totals"]["phases"] == 3
        assert body["equipment_totals"]["actual_hours"] == 260.0
        assert body["equipment_totals"]["est_hours"] == 280.0

        assert body["combined_actual_hours"] == 670.0
        assert body["combined_est_hours"] == 680.0
        assert body["combined_percent_used"] == pytest.approx(670.0 / 680.0)

    def test_phase_status_counts(self, client):
        body = client.get("/api/productivity/summary").json()
        # P_OVER_BOTH (over) -> OVER_BUDGET (worst across labor+equip)
        # P_BEHIND_LABOR (behind labor only)  -> BEHIND_PACE
        # P_LABOR_ON (on track labor only)    -> ON_TRACK
        # P_DONE (complete labor + equip)     -> COMPLETE
        # P_UNK_ZERO_EST (zero est)           -> UNKNOWN
        # P_EQUIP_ON (on track equip only)    -> ON_TRACK
        assert body["phases_over_budget"] == 1
        assert body["phases_behind_pace"] == 1
        assert body["phases_on_track"] == 2
        assert body["phases_complete"] == 1
        assert body["phases_unknown"] == 1

        total = (
            body["phases_over_budget"] + body["phases_behind_pace"]
            + body["phases_on_track"] + body["phases_complete"]
            + body["phases_unknown"]
        )
        assert total == body["total_phases"] == 6

        # Fractions add to 1.0
        sum_pct = (
            body["pct_over_budget"] + body["pct_behind_pace"]
            + body["pct_on_track"] + body["pct_complete"]
            + body["pct_unknown"]
        )
        assert sum_pct == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# /attention                                                                  #
# --------------------------------------------------------------------------- #


class TestAttention:
    def test_default_returns_only_problem_phases(self, client):
        body = client.get("/api/productivity/attention").json()

        # Only OVER_BUDGET + BEHIND_PACE rows should surface.
        # P_OVER_BOTH labor (sev = 80), P_OVER_BOTH equip (sev = 20),
        # P_BEHIND_LABOR (BEHIND_PACE).
        statuses = {row["status"] for row in body["items"]}
        assert statuses <= {"over_budget", "behind_pace"}

        # 3 problem rows.
        assert body["total"] == 3
        assert len(body["items"]) == 3

    def test_severity_sort_desc(self, client):
        body = client.get("/api/productivity/attention").json()
        sevs = [r["severity"] for r in body["items"]]
        assert sevs == sorted(sevs, reverse=True)

        # The labor over-budget row (180 vs 100 est) is the worst.
        top = body["items"][0]
        assert top["status"] == "over_budget"
        assert top["resource_kind"] == "labor"
        assert top["severity"] == 80.0

    def test_filter_by_resource_kind(self, client):
        body = client.get(
            "/api/productivity/attention?resource_kind=equipment"
        ).json()
        assert all(r["resource_kind"] == "equipment" for r in body["items"])
        assert body["total"] == 1

    def test_filter_by_status(self, client):
        body = client.get(
            "/api/productivity/attention?status=behind_pace"
        ).json()
        assert all(r["status"] == "behind_pace" for r in body["items"])
        assert body["total"] == 1
        assert body["items"][0]["phase"] == "P_BEHIND_LABOR"

    def test_top_n_caps_items_but_not_total(self, client):
        body = client.get("/api/productivity/attention?top_n=1").json()
        assert body["total"] == 3            # full count preserved
        assert len(body["items"]) == 1       # but list capped


# --------------------------------------------------------------------------- #
# /jobs/{job_id}                                                              #
# --------------------------------------------------------------------------- #


class TestJobDetail:
    def test_unknown_job_returns_404(self, client):
        r = client.get("/api/productivity/jobs/DOES-NOT-EXIST")
        assert r.status_code == 404

    def test_j1_returns_four_phases_with_rollups(self, client):
        r = client.get("/api/productivity/jobs/J1")
        assert r.status_code == 200
        body = r.json()

        assert body["id"] == "J1"
        assert len(body["phases"]) == 4

        # Labor rollup: 40+180+50+130 = 400 actual, est 400.
        assert body["labor_rollup"]["actual_hours"] == 400.0
        assert body["labor_rollup"]["est_hours"] == 400.0
        assert body["labor_rollup"]["percent_used"] == pytest.approx(1.0)

        # Equipment rollup: 120+110 = 230 actual, est 200.
        assert body["equipment_rollup"]["actual_hours"] == 230.0
        assert body["equipment_rollup"]["est_hours"] == 200.0

        # Status counts.
        assert body["phases_over_budget"] == 1
        assert body["phases_behind_pace"] == 1
        assert body["phases_on_track"] == 1
        assert body["phases_complete"] == 1

        # Phases sorted with the worst status first.
        first = body["phases"][0]
        assert first["worst_status"] == "over_budget"

    def test_j2_has_only_two_phases_and_no_labor_rollup_when_zero(
        self, client
    ):
        r = client.get("/api/productivity/jobs/J2")
        assert r.status_code == 200
        body = r.json()

        assert body["id"] == "J2"
        assert len(body["phases"]) == 2

        # Labor rollup exists (P_UNK row contributes 10 actual, 0 est).
        assert body["labor_rollup"] is not None
        assert body["labor_rollup"]["actual_hours"] == 10.0
        assert body["labor_rollup"]["est_hours"] == 0.0
        # Zero est => percent_used None
        assert body["labor_rollup"]["percent_used"] is None

        # Equipment rollup just has P_EQUIP_ON.
        assert body["equipment_rollup"]["actual_hours"] == 30.0
        assert body["equipment_rollup"]["est_hours"] == 80.0

    def test_url_with_whitespace_in_id_normalizes(self, client):
        # %20J1 -> " J1" -> stripped to "J1"
        r = client.get("/api/productivity/jobs/" + urllib.parse.quote(" J1"))
        assert r.status_code == 200
        assert r.json()["id"] == "J1"


# --------------------------------------------------------------------------- #
# Pace band override                                                          #
# --------------------------------------------------------------------------- #


class TestPaceBandOverride:
    def test_wide_band_keeps_behind_phase_on_track(self, client):
        # P_BEHIND_LABOR has used 50% of hours but only 20% complete.
        # Default band 10pp -> BEHIND_PACE. Bumping to 50pp moves it to
        # ON_TRACK.
        body = client.get(
            "/api/productivity/summary?pace_band_pct=50"
        ).json()
        assert body["phases_behind_pace"] == 0
        assert body["phases_on_track"] == 3
