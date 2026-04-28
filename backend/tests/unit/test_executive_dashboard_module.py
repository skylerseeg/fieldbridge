"""Tests for app.modules.executive_dashboard.

Strategy mirrors the per-module suites:
  1. Build a fresh SQLite DB per test via fixtures.
  2. Import ``app.services.excel_marts`` so every mart Table is registered
     on Base.metadata, then create_all() builds the real schema.
  3. Seed cross-mart data covering every pulse:
       - 4 WIP rows: one profitable balanced, one loss, one over-billed,
         one under-billed.
       - 3 schedule rows: one on-track, one at-risk (proj_end in 10
         days), one late (proj_end 20 days ago, < 100% complete).
       - 2 utilization tickets in the last 30 days, 1 stale (60 days)
         which falls outside the window.
       - 2 outlook bids (one ready_for_review, one upcoming),
         3 history bids (2 won, 1 lost) all bid this year.
       - 1 proposal, 2 vendors, 3 asset barcodes (1 retired).
       - 2 estimate_variance rows (last month + 3 months ago).
  4. Drive the API through TestClient with dependency overrides.

Assertions are exact counts so a regression in any aggregator can't
slip past — the rollup is the whole point of this module.
"""
from __future__ import annotations

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
from app.modules.executive_dashboard.router import (
    _default_engine,
    get_engine,
    get_tenant_id,
    router as exec_router,
)
from app.modules.executive_dashboard.schema import AttentionKind
from app.modules.executive_dashboard.service import (
    BILLING_BAND_PCT,
    LOSS_BAND_PCT,
    get_attention,
    get_summary,
    get_trend,
)


# Pinned at import time so the seed stays deterministic within a run.
NOW = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def seeded_engine(tmp_path) -> Engine:
    """SQLite file with every mart schema + a representative cross-mart seed."""
    url = f"sqlite:///{tmp_path / 'exec_dashboard_test.db'}"
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

    with engine.begin() as conn:
        # ---- mart_job_wip --------------------------------------------------
        # Numbers are chosen so the band tests fire predictably:
        #   - PROFITABLE BALANCED: contract 1.0M, GP 12% (well above LOSS band),
        #     OUB +$5k = 0.5% of contract (within BILLING band).
        #   - LOSS:       GP -8%; OUB 0.
        #   - OVER:       GP +5%; OUB +$200k = 20% of contract.
        #   - UNDER:      GP +5%; OUB -$80k  = 8%  of contract.
        wip_rows = [
            {
                "desc": "Job-PROFITABLE",
                "total_contract": 1_000_000.0,
                "contract_cost_td": 400_000.0,
                "contract_revenues_earned": 480_000.0,
                "est_gross_profit": 120_000.0,
                "est_gross_profit_pct": 0.12,
                "percent_complete": 0.48,
                "over_under_billings": 5_000.0,
            },
            {
                "desc": "Job-LOSS",
                "total_contract": 500_000.0,
                "contract_cost_td": 300_000.0,
                "contract_revenues_earned": 270_000.0,
                "est_gross_profit": -40_000.0,
                "est_gross_profit_pct": -0.08,
                "percent_complete": 0.55,
                "over_under_billings": 0.0,
            },
            {
                "desc": "Job-OVER",
                "total_contract": 1_000_000.0,
                "contract_cost_td": 400_000.0,
                "contract_revenues_earned": 400_000.0,
                "est_gross_profit": 50_000.0,
                "est_gross_profit_pct": 0.05,
                "percent_complete": 0.40,
                "over_under_billings": 200_000.0,
            },
            {
                "desc": "Job-UNDER",
                "total_contract": 1_000_000.0,
                "contract_cost_td": 400_000.0,
                "contract_revenues_earned": 480_000.0,
                "est_gross_profit": 50_000.0,
                "est_gross_profit_pct": 0.05,
                "percent_complete": 0.48,
                "over_under_billings": -80_000.0,
            },
        ]
        for r in wip_rows:
            conn.execute(
                text(
                    """
                    INSERT INTO mart_job_wip
                        (tenant_id, contract_job_description,
                         total_contract, contract_cost_td,
                         contract_revenues_earned,
                         est_gross_profit, est_gross_profit_pct,
                         percent_complete, over_under_billings)
                    VALUES (:tid, :desc, :total_contract, :contract_cost_td,
                            :contract_revenues_earned,
                            :est_gross_profit, :est_gross_profit_pct,
                            :percent_complete, :over_under_billings)
                    """
                ),
                {"tid": tenant_id, **r},
            )

        # ---- mart_job_schedule --------------------------------------------
        # On-track points to PROFITABLE; at-risk points to UNDER (proj_end
        # in 10 days, percent_complete only 0.48); LATE points to a job
        # that has no WIP row, so percent_complete defaults to 0.0.
        schedule_rows = [
            {
                "priority": 1,
                "job": "Job-PROFITABLE",
                "proj_end": (NOW + timedelta(days=120)).isoformat(),
            },
            {
                "priority": 2,
                "job": "Job-UNDER",
                "proj_end": (NOW + timedelta(days=10)).isoformat(),
            },
            {
                "priority": 3,
                "job": "Job-ORPHAN-LATE",
                "proj_end": (NOW - timedelta(days=20)).isoformat(),
            },
        ]
        for r in schedule_rows:
            conn.execute(
                text(
                    """
                    INSERT INTO mart_job_schedule
                        (tenant_id, priority, job, proj_end)
                    VALUES (:tid, :priority, :job, :proj_end)
                    """
                ),
                {"tid": tenant_id, **r},
            )

        # ---- mart_equipment_utilization -----------------------------------
        # 2 tickets inside 30-day window, 1 outside. Distinct trucks = 3.
        for i, (date, truck, price) in enumerate([
            (NOW - timedelta(days=5), "TRUCK-A", 1_000.0),
            (NOW - timedelta(days=20), "TRUCK-B", 2_500.0),
            (NOW - timedelta(days=60), "TRUCK-C", 9_999.0),
        ]):
            conn.execute(
                text(
                    """
                    INSERT INTO mart_equipment_utilization
                        (tenant_id, ticket_date, ticket, truck, qty,
                         units, price, extended_price)
                    VALUES (:tid, :date, :ticket, :truck, 1.0,
                            'hrs', :price, :price)
                    """
                ),
                {
                    "tid": tenant_id,
                    "date": date.isoformat(),
                    "ticket": f"T-{i}",
                    "truck": truck,
                    "price": price,
                },
            )

        # ---- mart_bids_outlook --------------------------------------------
        # bid_date inside the +30 day window for one row; the other has
        # ready_for_review = 1 but bid_date in the past.
        outlook_rows = [
            {
                "job": "OL-Upcoming",
                "owner": "DOT",
                "bid_type": "civil",
                "ready_for_review": 0,
                "bid_date": (NOW + timedelta(days=15)).isoformat(),
                "anticipated_bid_date": None,
            },
            {
                "job": "OL-Reviewed",
                "owner": "City",
                "bid_type": "civil",
                "ready_for_review": 1,
                "bid_date": (NOW - timedelta(days=5)).isoformat(),
                "anticipated_bid_date": None,
            },
        ]
        for r in outlook_rows:
            conn.execute(
                text(
                    """
                    INSERT INTO mart_bids_outlook
                        (tenant_id, job, owner, bid_type,
                         ready_for_review, bid_date, anticipated_bid_date)
                    VALUES (:tid, :job, :owner, :bid_type,
                            :ready_for_review, :bid_date, :anticipated_bid_date)
                    """
                ),
                {"tid": tenant_id, **r},
            )

        # ---- mart_bids_history --------------------------------------------
        # All YTD: 3 submitted, 2 won (won field >0).
        year_start = datetime(NOW.year, 1, 1)
        history_rows = [
            (
                "BH-1",
                (year_start + timedelta(days=30)).isoformat(),
                1.0,
            ),
            (
                "BH-2",
                (year_start + timedelta(days=60)).isoformat(),
                1.0,
            ),
            (
                "BH-3",
                (year_start + timedelta(days=90)).isoformat(),
                0.0,
            ),
        ]
        for job, bid_date, won in history_rows:
            conn.execute(
                text(
                    """
                    INSERT INTO mart_bids_history
                        (tenant_id, job, bid_date, won)
                    VALUES (:tid, :job, :bid_date, :won)
                    """
                ),
                {"tid": tenant_id, "job": job, "bid_date": bid_date, "won": won},
            )

        # ---- mart_proposals -----------------------------------------------
        conn.execute(
            text(
                """
                INSERT INTO mart_proposals
                    (tenant_id, job, owner, bid_type)
                VALUES (:tid, 'PR-1', 'DOT', 'civil')
                """
            ),
            {"tid": tenant_id},
        )

        # ---- mart_vendors -------------------------------------------------
        for i, name in enumerate(["AcmeRent", "PavingPro"]):
            conn.execute(
                text(
                    """
                    INSERT INTO mart_vendors
                        (tenant_id, _row_hash, name, firm_type)
                    VALUES (:tid, :rh, :name, 'supplier')
                    """
                ),
                {"tid": tenant_id, "rh": f"vendor-{i}", "name": name},
            )

        # ---- mart_asset_barcodes ------------------------------------------
        for barcode, retired in [(1, None), (2, None), (3, NOW - timedelta(days=10))]:
            conn.execute(
                text(
                    """
                    INSERT INTO mart_asset_barcodes
                        (tenant_id, barcode, manufacturer, retired_date)
                    VALUES (:tid, :barcode, 'Test', :retired)
                    """
                ),
                {
                    "tid": tenant_id,
                    "barcode": barcode,
                    "retired": retired.isoformat() if retired else None,
                },
            )

        # ---- mart_estimate_variance ---------------------------------------
        # One in current month, one 3 months ago. Both inside the 12-month
        # window so the trend should pick them up.
        last_month = NOW.replace(day=1) - timedelta(days=1)
        three_months_ago = (NOW.replace(day=1) - timedelta(days=90)).replace(day=1)
        for cm, est, act in [
            (last_month, 100_000.0, 90_000.0),
            (three_months_ago, 80_000.0, 88_000.0),
        ]:
            conn.execute(
                text(
                    """
                    INSERT INTO mart_estimate_variance
                        (tenant_id, job_grouping, close_month,
                         estimate, actual, variance, percent)
                    VALUES (:tid, :job, :cm, :est, :act,
                            :variance, :percent)
                    """
                ),
                {
                    "tid": tenant_id,
                    "job": f"job-{cm.isoformat()}",
                    "cm": cm.isoformat(),
                    "est": est,
                    "act": act,
                    "variance": act - est,
                    "percent": (act - est) / est if est else 0.0,
                },
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
    app.include_router(exec_router, prefix="/api/executive-dashboard")
    app.dependency_overrides[get_engine] = lambda: seeded_engine
    app.dependency_overrides[get_tenant_id] = lambda: seeded_tenant_id
    _default_engine.cache_clear()
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# Service-level tests                                                         #
# --------------------------------------------------------------------------- #


class TestSummary:
    """get_summary aggregates each pulse correctly."""

    def test_financial_pulse_totals(self, seeded_engine, seeded_tenant_id):
        s = get_summary(seeded_engine, seeded_tenant_id, now=NOW)
        f = s.financial
        # 4 WIP rows seeded.
        assert f.active_jobs == 4
        # 1.0M + 0.5M + 1.0M + 1.0M = 3.5M
        assert f.total_contract_value == pytest.approx(3_500_000.0)
        # 480k + 270k + 400k + 480k = 1.63M
        assert f.total_revenue_earned == pytest.approx(1_630_000.0)
        # 120k + (-40k) + 50k + 50k = 180k
        assert f.total_estimated_gross_profit == pytest.approx(180_000.0)
        # weighted GP% = 180k / 3.5M
        assert f.weighted_gross_profit_pct == pytest.approx(180_000.0 / 3_500_000.0)

    def test_financial_pulse_billing_buckets(self, seeded_engine, seeded_tenant_id):
        s = get_summary(seeded_engine, seeded_tenant_id, now=NOW)
        f = s.financial
        # PROFITABLE balanced (0.5%), LOSS balanced (0% on file), OVER (20%),
        # UNDER (8%).
        assert f.over_billed_jobs == 1
        assert f.under_billed_jobs == 1
        assert f.balanced_jobs == 2
        # 5k + 0 + 200k + (-80k) = 125k
        assert f.total_over_under_billings == pytest.approx(125_000.0)

    def test_operations_pulse(self, seeded_engine, seeded_tenant_id):
        s = get_summary(seeded_engine, seeded_tenant_id, now=NOW)
        o = s.operations
        # 3 distinct schedule rows
        assert o.scheduled_jobs == 3
        # Job-UNDER ends in 10 days, percent_complete 0.48 -> at_risk
        assert o.jobs_at_risk == 1
        # Job-ORPHAN-LATE ended 20 days ago, no WIP -> percent_complete 0
        assert o.jobs_late == 1
        # 3 distinct trucks ever, 2 inside the 30-day window
        assert o.total_equipment == 3
        assert o.equipment_tickets_30d == 2
        assert o.equipment_revenue_30d == pytest.approx(3_500.0)

    def test_pipeline_pulse(self, seeded_engine, seeded_tenant_id):
        s = get_summary(seeded_engine, seeded_tenant_id, now=NOW)
        p = s.pipeline
        assert p.bids_in_pipeline == 2
        assert p.bids_ready_for_review == 1
        assert p.upcoming_bids_30d == 1
        assert p.bids_submitted_ytd == 3
        assert p.bids_won_ytd == 2
        assert p.win_rate_ytd == pytest.approx(2 / 3)
        assert p.proposals_outstanding == 1

    def test_roster_pulse(self, seeded_engine, seeded_tenant_id):
        s = get_summary(seeded_engine, seeded_tenant_id, now=NOW)
        r = s.roster
        assert r.total_vendors == 2
        assert r.total_assets == 3
        assert r.retired_assets == 1


class TestAttention:
    """Top-N flagged-job ranking."""

    def test_flags_loss_late_overbilled_underbilled(
        self, seeded_engine, seeded_tenant_id
    ):
        a = get_attention(seeded_engine, seeded_tenant_id, now=NOW, top_n=20)
        kinds = {item.kind for item in a.items}
        # Each axis fires at least once given the seed.
        assert AttentionKind.LOSS in kinds
        assert AttentionKind.LATE in kinds
        assert AttentionKind.OVER_BILLED in kinds
        assert AttentionKind.UNDER_BILLED in kinds
        # Job-UNDER is at_risk (proj_end in 10 days, < 100% complete).
        assert AttentionKind.AT_RISK in kinds

    def test_severity_sort_descending(self, seeded_engine, seeded_tenant_id):
        a = get_attention(seeded_engine, seeded_tenant_id, now=NOW, top_n=20)
        sevs = [i.severity for i in a.items]
        assert sevs == sorted(sevs, reverse=True)

    def test_top_n_truncates(self, seeded_engine, seeded_tenant_id):
        full = get_attention(seeded_engine, seeded_tenant_id, now=NOW, top_n=20)
        # The seed always produces > 2 items (LOSS + LATE + OVER + UNDER + AT_RISK)
        assert len(full.items) > 2
        small = get_attention(seeded_engine, seeded_tenant_id, now=NOW, top_n=2)
        assert len(small.items) == 2
        # First two items are unchanged after truncation.
        assert [i.kind for i in small.items] == [i.kind for i in full.items[:2]]

    def test_loss_flag_uses_band(self, seeded_engine, seeded_tenant_id):
        # Sanity: the LOSS_BAND constant matches what the seed depends on.
        # Job-LOSS has -8% GP, well past -2%.
        assert LOSS_BAND_PCT == 2.0
        a = get_attention(seeded_engine, seeded_tenant_id, now=NOW, top_n=20)
        loss_jobs = [i.job for i in a.items if i.kind is AttentionKind.LOSS]
        assert any("Job-LOSS" in j for j in loss_jobs)

    def test_billing_flag_uses_band(self, seeded_engine, seeded_tenant_id):
        assert BILLING_BAND_PCT == 2.0
        a = get_attention(seeded_engine, seeded_tenant_id, now=NOW, top_n=20)
        over = [i for i in a.items if i.kind is AttentionKind.OVER_BILLED]
        under = [i for i in a.items if i.kind is AttentionKind.UNDER_BILLED]
        assert any("Job-OVER" in i.job for i in over)
        assert any("Job-UNDER" in i.job for i in under)
        # PROFITABLE is at 0.5% of contract -> within band, must NOT appear
        # on the billing axis.
        billing_kinds = {AttentionKind.OVER_BILLED, AttentionKind.UNDER_BILLED}
        profitable_billing = [
            i for i in a.items
            if "Job-PROFITABLE" in i.job and i.kind in billing_kinds
        ]
        assert profitable_billing == []


class TestTrend:
    """12-month revenue trend."""

    def test_trend_window_size(self, seeded_engine, seeded_tenant_id):
        t = get_trend(seeded_engine, seeded_tenant_id, now=NOW, months=12)
        assert len(t.months) == 12
        # Months are oldest-first; final entry is the current month.
        assert t.months[-1].month == f"{NOW.year:04d}-{NOW.month:02d}"

    def test_trend_buckets_estimate_variance(
        self, seeded_engine, seeded_tenant_id
    ):
        t = get_trend(seeded_engine, seeded_tenant_id, now=NOW, months=12)
        # We seeded 100k estimate / 90k actual in the last-month bucket.
        # Find that month in the trend and check the totals.
        last_month = (NOW.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        match = next(p for p in t.months if p.month == last_month)
        assert match.estimate == pytest.approx(100_000.0)
        assert match.actual == pytest.approx(90_000.0)


# --------------------------------------------------------------------------- #
# HTTP-level tests                                                            #
# --------------------------------------------------------------------------- #


class TestHTTP:
    """The same assertions but routed through TestClient."""

    def test_summary_endpoint(self, client):
        resp = client.get("/api/executive-dashboard/summary")
        assert resp.status_code == 200
        body = resp.json()
        # Spot-check the four pulse blocks are present and typed.
        assert body["financial"]["active_jobs"] == 4
        assert body["operations"]["total_equipment"] == 3
        assert body["pipeline"]["bids_submitted_ytd"] == 3
        assert body["roster"]["retired_assets"] == 1
        assert "as_of" in body

    def test_attention_endpoint_default(self, client):
        resp = client.get("/api/executive-dashboard/attention")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["items"], list)
        assert len(body["items"]) > 0
        # Every kind is present in the enum.
        valid = {k.value for k in AttentionKind}
        for item in body["items"]:
            assert item["kind"] in valid

    def test_attention_top_n_query(self, client):
        resp = client.get("/api/executive-dashboard/attention?top_n=1")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    def test_attention_top_n_validates_bounds(self, client):
        # top_n=0 is below ge=1 -> 422
        resp = client.get("/api/executive-dashboard/attention?top_n=0")
        assert resp.status_code == 422

    def test_trend_endpoint(self, client):
        resp = client.get("/api/executive-dashboard/trend?months=6")
        assert resp.status_code == 200
        assert len(resp.json()["months"]) == 6
