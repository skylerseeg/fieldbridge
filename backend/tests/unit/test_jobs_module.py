"""Tests for app.modules.jobs.

Strategy mirrors the other mart-backed modules:
  1. Fresh SQLite DB per test via fixtures.
  2. Register every mart Table against Base.metadata, create_all().
  3. Seed five canonical jobs spanning every combination of statuses,
     plus a historical estimate_variance tail so estimate_accuracy has
     real numbers to aggregate.
  4. Drive the API through TestClient with dependency overrides.

Canonical seed (anchored to NOW so schedule math stays stable):

  JOB-PROF-ON     WIP + schedule  profitable  on_schedule   balanced
  JOB-PROF-RISK   WIP + schedule  profitable  at_risk       over_billed
  JOB-LOSS-LATE   WIP + schedule  loss        late          under_billed
  JOB-BE-NODATE   WIP only        breakeven   no_schedule   balanced
  JOB-ORPHAN-SCH  schedule only   unknown     on_schedule   unknown

Historical variance rows populate estimate_accuracy for JOB-PROF-ON
only — the other jobs have no history, which exercises jobs_tracked
counting.
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

# Register every mart Table against Base.metadata.
import app.services.excel_marts  # noqa: F401
from app.core.database import Base
from app.models.tenant import SubscriptionTier, Tenant, TenantStatus
from app.modules.jobs.router import (
    _default_engine,
    get_engine,
    get_tenant_id,
    router as jobs_router,
)
from app.modules.jobs.service import _strip_job_key


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


NOW = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


@pytest.fixture
def seeded_engine(tmp_path) -> Engine:
    url = f"sqlite:///{tmp_path / 'jobs_test.db'}"
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

    # -- WIP rows ---------------------------------------------------------
    wip_rows = [
        # JOB-PROF-ON: +20% margin, balanced billings, 50% complete.
        {
            "contract_job_description": " JOB-PROF-ON",  # leading space on purpose
            "total_contract": 1_000_000.0,
            "contract_cost_td": 400_000.0,
            "est_cost_to_complete": 400_000.0,
            "est_total_cost": 800_000.0,
            "est_gross_profit": 200_000.0,
            "est_gross_profit_pct": 0.20,
            "percent_complete": 0.50,
            "gain_fade_from_prior_mth": 0.0,
            "billings_to_date": 500_000.0,
            "over_under_billings": 5_000.0,   # 0.5% of contract -> balanced
            "contract_revenues_earned": 495_000.0,
            "gross_profit_loss_td": 95_000.0,
            "gross_profit_pct_td": 0.1919,
        },
        # JOB-PROF-RISK: profitable, proj_end in 10 days, billed 5% ahead.
        {
            "contract_job_description": "JOB-PROF-RISK",
            "total_contract": 2_000_000.0,
            "contract_cost_td": 1_200_000.0,
            "est_cost_to_complete": 400_000.0,
            "est_total_cost": 1_600_000.0,
            "est_gross_profit": 400_000.0,
            "est_gross_profit_pct": 0.20,
            "percent_complete": 0.75,
            "gain_fade_from_prior_mth": 0.0,
            "billings_to_date": 1_600_000.0,
            "over_under_billings": 100_000.0,   # 5% of contract -> over
            "contract_revenues_earned": 1_500_000.0,
            "gross_profit_loss_td": 300_000.0,
            "gross_profit_pct_td": 0.20,
        },
        # JOB-LOSS-LATE: loss, past proj_end, under-billed.
        {
            "contract_job_description": "JOB-LOSS-LATE",
            "total_contract": 500_000.0,
            "contract_cost_td": 525_000.0,
            "est_cost_to_complete": 25_000.0,
            "est_total_cost": 550_000.0,
            "est_gross_profit": -50_000.0,
            "est_gross_profit_pct": -0.10,
            "percent_complete": 0.90,
            "gain_fade_from_prior_mth": -10_000.0,
            "billings_to_date": 400_000.0,
            "over_under_billings": -50_000.0,    # -10% of contract -> under
            "contract_revenues_earned": 450_000.0,
            "gross_profit_loss_td": -75_000.0,
            "gross_profit_pct_td": -0.1667,
        },
        # JOB-BE-NODATE: breakeven (±2%), no schedule row.
        {
            "contract_job_description": "JOB-BE-NODATE",
            "total_contract": 750_000.0,
            "contract_cost_td": 300_000.0,
            "est_cost_to_complete": 440_000.0,
            "est_total_cost": 740_000.0,
            "est_gross_profit": 10_000.0,
            "est_gross_profit_pct": 0.013,     # 1.3% -> breakeven
            "percent_complete": 0.40,
            "gain_fade_from_prior_mth": 0.0,
            "billings_to_date": 300_000.0,
            "over_under_billings": 0.0,
            "contract_revenues_earned": 300_000.0,
            "gross_profit_loss_td": 0.0,
            "gross_profit_pct_td": 0.0,
        },
    ]

    insert_wip = text(
        """
        INSERT INTO mart_job_wip
            (tenant_id, contract_job_description, total_contract,
             contract_cost_td, est_cost_to_complete, est_total_cost,
             est_gross_profit, est_gross_profit_pct, percent_complete,
             gain_fade_from_prior_mth, billings_to_date,
             over_under_billings, contract_revenues_earned,
             gross_profit_loss_td, gross_profit_pct_td)
        VALUES (:tenant_id, :contract_job_description, :total_contract,
                :contract_cost_td, :est_cost_to_complete, :est_total_cost,
                :est_gross_profit, :est_gross_profit_pct, :percent_complete,
                :gain_fade_from_prior_mth, :billings_to_date,
                :over_under_billings, :contract_revenues_earned,
                :gross_profit_loss_td, :gross_profit_pct_td)
        """
    )

    # -- Schedule rows ----------------------------------------------------
    schedule_rows = [
        # JOB-PROF-ON — proj_end 120d out -> on_schedule.
        {
            "priority": 1,
            "job": " JOB-PROF-ON",   # leading space intentional
            "start": _iso(NOW - timedelta(days=90)),
            "proj_end": _iso(NOW + timedelta(days=120)),
            "milestone": None,
            "reason": "Cruising",
            "priority_departments": None,
            "liquidated_damage": None,
            "chad_wants": None,
        },
        # JOB-PROF-RISK — proj_end 10d out -> at_risk.
        {
            "priority": 2,
            "job": "JOB-PROF-RISK",
            "start": _iso(NOW - timedelta(days=180)),
            "proj_end": _iso(NOW + timedelta(days=10)),
            "milestone": None,
            "reason": "Finish paving",
            "priority_departments": None,
            "liquidated_damage": None,
            "chad_wants": None,
        },
        # JOB-LOSS-LATE — proj_end 20d in the past, 90% complete -> late.
        {
            "priority": 3,
            "job": "JOB-LOSS-LATE",
            "start": _iso(NOW - timedelta(days=200)),
            "proj_end": _iso(NOW - timedelta(days=20)),
            "milestone": None,
            "reason": "Weather delays",
            "priority_departments": None,
            "liquidated_damage": 5_000.0,
            "chad_wants": None,
        },
        # JOB-ORPHAN-SCH — only exists in schedule, on_schedule.
        {
            "priority": 4,
            "job": "JOB-ORPHAN-SCH",
            "start": _iso(NOW - timedelta(days=5)),
            "proj_end": _iso(NOW + timedelta(days=180)),
            "milestone": None,
            "reason": "Just awarded",
            "priority_departments": None,
            "liquidated_damage": None,
            "chad_wants": None,
        },
    ]

    insert_sched = text(
        """
        INSERT INTO mart_job_schedule
            (tenant_id, priority, job, start, proj_end, milestone,
             reason, priority_departments, liquidated_damage, chad_wants)
        VALUES (:tenant_id, :priority, :job, :start, :proj_end, :milestone,
                :reason, :priority_departments, :liquidated_damage,
                :chad_wants)
        """
    )

    # -- Estimate-variance rows (for JOB-PROF-ON only) --------------------
    # Two close months. Variance = estimate - actual per mart convention.
    variance_rows = [
        {
            "job_grouping": "JOB-PROF-ON",
            "close_month": _iso(datetime(2024, 1, 1)),
            "estimate": 100_000.0,
            "actual": 95_000.0,
            "variance": 5_000.0,        # 5% under -> +5% variance_pct
            "percent": 0.05,
        },
        {
            "job_grouping": "JOB-PROF-ON",
            "close_month": _iso(datetime(2024, 7, 1)),
            "estimate": 200_000.0,
            "actual": 220_000.0,
            "variance": -20_000.0,      # 10% over -> -10% variance_pct
            "percent": -0.10,
        },
    ]

    insert_var = text(
        """
        INSERT INTO mart_estimate_variance
            (tenant_id, job_grouping, close_month, estimate, actual,
             variance, percent)
        VALUES (:tenant_id, :job_grouping, :close_month, :estimate,
                :actual, :variance, :percent)
        """
    )

    with engine.begin() as conn:
        for w in wip_rows:
            conn.execute(insert_wip, {"tenant_id": tenant_id, **w})
        for s in schedule_rows:
            conn.execute(insert_sched, {"tenant_id": tenant_id, **s})
        for v in variance_rows:
            conn.execute(insert_var, {"tenant_id": tenant_id, **v})

    return engine


@pytest.fixture
def seeded_tenant_id(seeded_engine: Engine) -> str:
    with sessionmaker(seeded_engine)() as s:
        tenant = s.execute(
            text("SELECT id FROM tenants WHERE slug = 'vancon'")
        ).scalar_one()
    return tenant


@pytest.fixture
def client(seeded_engine: Engine, seeded_tenant_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(jobs_router, prefix="/api/jobs")

    app.dependency_overrides[get_engine] = lambda: seeded_engine
    app.dependency_overrides[get_tenant_id] = lambda: seeded_tenant_id

    _default_engine.cache_clear()

    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# Pure helper — _strip_job_key                                                #
# --------------------------------------------------------------------------- #


class TestStripJobKey:
    def test_strips_leading_whitespace(self):
        assert _strip_job_key(" 2231. UDOT Bangerter") == "2231. UDOT Bangerter"

    def test_collapses_internal_whitespace(self):
        assert _strip_job_key("  JOB   X  ") == "JOB X"

    def test_none_returns_empty(self):
        assert _strip_job_key(None) == ""


# --------------------------------------------------------------------------- #
# /summary                                                                    #
# --------------------------------------------------------------------------- #


class TestSummary:
    def test_kpi_tiles(self, client: TestClient):
        resp = client.get("/api/jobs/summary")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        # 4 WIP rows + 1 schedule-only = 5 total jobs.
        assert body["total_jobs"] == 5
        assert body["jobs_with_wip"] == 4
        # jobs_scheduled counts anything whose status isn't UNKNOWN, which
        # here means every schedule mart row (3 matched to WIP + 1 orphan).
        assert body["jobs_scheduled"] == 4

        # Contract totals across WIP:
        # 1M + 2M + 500k + 750k = 4.25M
        assert body["total_contract_value"] == pytest.approx(4_250_000.0)

        # Schedule breakdown:
        # JOB-PROF-ON (120d) -> on_schedule
        # JOB-ORPHAN-SCH (180d, no WIP) -> on_schedule
        # JOB-PROF-RISK (10d) -> at_risk
        # JOB-LOSS-LATE (-20d, 90% complete) -> late
        # JOB-BE-NODATE (no sched) -> no_schedule (hence not counted on/at_risk/late)
        assert body["jobs_on_schedule"] == 2
        assert body["jobs_at_risk"] == 1
        assert body["jobs_late"] == 1

        # Financial breakdown (from WIP margins, 2% breakeven band):
        # JOB-PROF-ON (20%)    -> profitable
        # JOB-PROF-RISK (20%)  -> profitable
        # JOB-LOSS-LATE (-10%) -> loss
        # JOB-BE-NODATE (1.3%) -> breakeven
        # JOB-ORPHAN-SCH (None)-> unknown (not counted)
        assert body["jobs_profitable"] == 2
        assert body["jobs_breakeven"] == 1
        assert body["jobs_loss"] == 1

        # Billing breakdown (2% of contract threshold):
        # JOB-PROF-ON   +5k / 1M = 0.5% -> balanced
        # JOB-PROF-RISK +100k / 2M = 5% -> over
        # JOB-LOSS-LATE -50k / 500k = 10% -> under
        # JOB-BE-NODATE  0 -> balanced
        # JOB-ORPHAN-SCH no WIP -> unknown
        assert body["jobs_over_billed"] == 1
        assert body["jobs_under_billed"] == 1
        assert body["jobs_balanced"] == 2

        # Weighted margin: total GP TD / total revenue earned
        # GP TD = 95k + 300k + (-75k) + 0 = 320k
        # Revenue = 495k + 1.5M + 450k + 300k = 2.745M
        assert body["weighted_avg_margin_pct"] == pytest.approx(
            320_000.0 / 2_745_000.0 * 100.0
        )

    def test_wider_at_risk_days_pushes_job_on_to_at_risk(
        self, client: TestClient,
    ):
        # With at_risk_days=200, JOB-PROF-ON (120d) flips to at_risk,
        # and JOB-ORPHAN-SCH (180d) flips too.
        resp = client.get("/api/jobs/summary?at_risk_days=200")
        body = resp.json()
        assert body["jobs_at_risk"] == 3   # was 1
        assert body["jobs_on_schedule"] == 0


# --------------------------------------------------------------------------- #
# /list                                                                       #
# --------------------------------------------------------------------------- #


class TestList:
    def test_pagination_and_total(self, client: TestClient):
        resp = client.get("/api/jobs/list?page=1&page_size=2")
        body = resp.json()
        assert resp.status_code == 200
        assert body["total"] == 5
        assert body["page"] == 1
        assert body["page_size"] == 2
        assert len(body["items"]) == 2

    def test_filter_schedule_at_risk(self, client: TestClient):
        resp = client.get("/api/jobs/list?schedule_status=at_risk")
        ids = {i["id"] for i in resp.json()["items"]}
        assert ids == {"JOB-PROF-RISK"}

    def test_filter_schedule_late(self, client: TestClient):
        resp = client.get("/api/jobs/list?schedule_status=late")
        ids = {i["id"] for i in resp.json()["items"]}
        assert ids == {"JOB-LOSS-LATE"}

    def test_filter_schedule_no_schedule(self, client: TestClient):
        resp = client.get("/api/jobs/list?schedule_status=no_schedule")
        ids = {i["id"] for i in resp.json()["items"]}
        assert ids == {"JOB-BE-NODATE"}

    def test_filter_financial_profitable(self, client: TestClient):
        resp = client.get("/api/jobs/list?financial_status=profitable")
        ids = {i["id"] for i in resp.json()["items"]}
        assert ids == {"JOB-PROF-ON", "JOB-PROF-RISK"}

    def test_filter_financial_loss(self, client: TestClient):
        resp = client.get("/api/jobs/list?financial_status=loss")
        ids = {i["id"] for i in resp.json()["items"]}
        assert ids == {"JOB-LOSS-LATE"}

    def test_filter_billing_over_billed(self, client: TestClient):
        resp = client.get("/api/jobs/list?billing_status=over_billed")
        ids = {i["id"] for i in resp.json()["items"]}
        assert ids == {"JOB-PROF-RISK"}

    def test_filter_billing_under_billed(self, client: TestClient):
        resp = client.get("/api/jobs/list?billing_status=under_billed")
        ids = {i["id"] for i in resp.json()["items"]}
        assert ids == {"JOB-LOSS-LATE"}

    def test_search_substring(self, client: TestClient):
        resp = client.get("/api/jobs/list?search=prof")
        ids = {i["id"] for i in resp.json()["items"]}
        assert ids == {"JOB-PROF-ON", "JOB-PROF-RISK"}

    def test_sort_by_est_gross_profit_desc(self, client: TestClient):
        resp = client.get(
            "/api/jobs/list?sort_by=est_gross_profit&sort_dir=desc"
        )
        items = resp.json()["items"]
        # PROF-RISK (400k) > PROF-ON (200k) > BE-NODATE (10k) > LOSS-LATE (-50k)
        # > ORPHAN (None, last)
        assert items[0]["id"] == "JOB-PROF-RISK"
        assert items[1]["id"] == "JOB-PROF-ON"
        assert items[-1]["id"] == "JOB-ORPHAN-SCH"

    def test_sort_by_schedule_days_to_end_asc(self, client: TestClient):
        resp = client.get(
            "/api/jobs/list?sort_by=schedule_days_to_end&sort_dir=asc"
        )
        items = resp.json()["items"]
        # LOSS-LATE (-20) < PROF-RISK (10) < PROF-ON (120) < ORPHAN-SCH (180)
        # < BE-NODATE (None, last)
        assert items[0]["id"] == "JOB-LOSS-LATE"
        assert items[-1]["id"] == "JOB-BE-NODATE"


# --------------------------------------------------------------------------- #
# /{job_id}                                                                   #
# --------------------------------------------------------------------------- #


class TestDetail:
    def test_detail_strips_leading_space_from_mart(self, client: TestClient):
        # Mart stored the job as ' JOB-PROF-ON' (leading space) — the API
        # should resolve it via the stripped id.
        resp = client.get("/api/jobs/JOB-PROF-ON")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == "JOB-PROF-ON"
        assert body["priority"] == 1
        assert body["financial_status"] == "profitable"
        assert body["schedule_status"] == "on_schedule"
        assert body["billing_status"] == "balanced"
        assert body["reason"] == "Cruising"
        assert body["est_cost_to_complete"] == pytest.approx(400_000.0)

    def test_detail_estimate_history_sorted(self, client: TestClient):
        resp = client.get("/api/jobs/JOB-PROF-ON")
        hist = resp.json()["estimate_history"]
        assert len(hist) == 2
        # Ascending close_month.
        assert hist[0]["close_month"] < hist[1]["close_month"]
        # First row: estimate 100k, actual 95k, variance +5k -> +5%.
        assert hist[0]["variance_pct"] == pytest.approx(5.0)
        # Second row: estimate 200k, actual 220k, variance -20k -> -10%.
        assert hist[1]["variance_pct"] == pytest.approx(-10.0)

    def test_detail_schedule_only_job(self, client: TestClient):
        resp = client.get("/api/jobs/JOB-ORPHAN-SCH")
        body = resp.json()
        assert body["total_contract"] is None
        assert body["financial_status"] == "unknown"
        assert body["schedule_status"] == "on_schedule"
        assert body["estimate_history"] == []

    def test_detail_wip_only_job(self, client: TestClient):
        resp = client.get("/api/jobs/JOB-BE-NODATE")
        body = resp.json()
        assert body["schedule_status"] == "no_schedule"
        assert body["priority"] is None
        assert body["financial_status"] == "breakeven"

    def test_detail_404_on_unknown(self, client: TestClient):
        resp = client.get("/api/jobs/GHOST-JOB")
        assert resp.status_code == 404

    def test_detail_url_with_spaces_resolves(self, client: TestClient):
        # Even if the caller includes whitespace in the URL, service
        # normalizes. This mimics real-world job names like "2231. UDOT".
        resp = client.get(
            "/api/jobs/" + urllib.parse.quote("JOB-PROF-ON")
        )
        assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# /insights                                                                   #
# --------------------------------------------------------------------------- #


class TestInsights:
    def test_schedule_breakdown(self, client: TestClient):
        resp = client.get("/api/jobs/insights")
        assert resp.status_code == 200, resp.text
        body = resp.json()["schedule_breakdown"]
        assert body == {
            "on_schedule": 2,
            "at_risk": 1,
            "late": 1,
            "no_schedule": 1,
            "unknown": 0,
        }

    def test_financial_breakdown(self, client: TestClient):
        resp = client.get("/api/jobs/insights")
        body = resp.json()["financial_breakdown"]
        assert body == {
            "profitable": 2,
            "breakeven": 1,
            "loss": 1,
            "unknown": 1,   # JOB-ORPHAN-SCH has no margin
        }

    def test_billing_metrics(self, client: TestClient):
        resp = client.get("/api/jobs/insights")
        body = resp.json()["billing_metrics"]
        assert body["over_billed_count"] == 1
        assert body["under_billed_count"] == 1
        assert body["balanced_count"] == 2
        assert body["unknown_count"] == 1
        assert body["total_over_billed"] == pytest.approx(100_000.0)
        assert body["total_under_billed"] == pytest.approx(50_000.0)

    def test_estimate_accuracy(self, client: TestClient):
        resp = client.get("/api/jobs/insights")
        body = resp.json()["estimate_accuracy"]
        assert body["samples"] == 2
        assert body["jobs_tracked"] == 1
        # Mean of (+5%, -10%) = -2.5%
        assert body["avg_variance_pct"] == pytest.approx(-2.5)
        # Mean of (5%, 10%) = 7.5%
        assert body["avg_abs_variance_pct"] == pytest.approx(7.5)

    def test_top_profit_and_loss(self, client: TestClient):
        resp = client.get("/api/jobs/insights")
        body = resp.json()
        profits = [p["id"] for p in body["top_profit"]]
        # Sorted desc by est_gross_profit.
        assert profits == ["JOB-PROF-RISK", "JOB-PROF-ON", "JOB-BE-NODATE"]
        losses = [l["id"] for l in body["top_loss"]]
        assert losses == ["JOB-LOSS-LATE"]

    def test_top_over_and_under_billed(self, client: TestClient):
        resp = client.get("/api/jobs/insights")
        body = resp.json()
        assert [o["id"] for o in body["top_over_billed"]] == ["JOB-PROF-RISK"]
        assert [u["id"] for u in body["top_under_billed"]] == ["JOB-LOSS-LATE"]

    def test_top_n_caps_lists(self, client: TestClient):
        resp = client.get("/api/jobs/insights?top_n=1")
        body = resp.json()
        assert len(body["top_profit"]) <= 1

    def test_insights_echoes_tunables(self, client: TestClient):
        resp = client.get(
            "/api/jobs/insights?at_risk_days=60&breakeven_band_pct=5"
            "&billing_balance_pct=4"
        )
        body = resp.json()
        assert body["at_risk_days"] == 60
        assert body["breakeven_band_pct"] == pytest.approx(5.0)
        assert body["billing_balance_pct"] == pytest.approx(4.0)
