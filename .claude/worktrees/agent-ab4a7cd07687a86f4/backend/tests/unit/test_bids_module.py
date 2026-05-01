"""Tests for app.modules.bids.

Strategy mirrors the other mart-backed modules:
  1. Fresh SQLite DB per test via fixtures.
  2. Register every mart Table against Base.metadata, create_all().
  3. Seed a small, canonical set of bids spanning every outcome,
     margin tier, and competition tier. Seed a couple of outlook
     rows so the summary pipeline tile is non-zero.
  4. Drive the API through TestClient with dependency overrides.

Canonical seed — eight bids across outcome / margin / competition:

  Job              was_bid rank vancon low  number_bidders  outcome       margin_tier  comp_tier
  Alpha Tunnel     T       1    100    100  1               WON           WINNER       SOLO
  Bravo Bridge     T       1    200    200  5               WON           WINNER       TYPICAL
  Charlie Culvert  T       2    103    100  2               LOST          CLOSE        LIGHT
  Delta Drain      T       3    108    100  3               LOST          MODERATE     LIGHT
  Echo Ease        T       4    150    100  8               LOST          WIDE         CROWDED
  Foxtrot Flyover  F       -    -      -    -               NO_BID        UNKNOWN      UNKNOWN
  Golf Gap         T       -    100    100  -               UNKNOWN       UNKNOWN      UNKNOWN
  Hotel Hill       T       2    100    -    4               LOST          UNKNOWN      TYPICAL

Thresholds used throughout the tests are the library defaults
(close_max=0.03, moderate_max=0.10, light_max=3, typical_max=6).
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import sessionmaker

# Register every mart Table against Base.metadata.
import app.services.excel_marts  # noqa: F401
from app.core.database import Base
from app.models.tenant import SubscriptionTier, Tenant, TenantStatus
from app.modules.bids.router import (
    _default_engine,
    get_engine,
    get_tenant_id,
    router as bids_router,
)
from app.modules.bids.schema import (
    BidOutcome,
    CompetitionTier,
    MarginTier,
)
from app.modules.bids.service import (
    _bid_id,
    _competition_tier,
    _margin_tier,
    _outcome,
    _percent_over,
    _to_bool,
    _truthy_flag,
)


# --------------------------------------------------------------------------- #
# Canonical seed                                                              #
# --------------------------------------------------------------------------- #


SEEDS: list[dict] = [
    # WON / WINNER / SOLO
    {
        "job": "Alpha Tunnel",
        "bid_date": datetime(2025, 1, 1),
        "was_bid": True,
        "owner": "WSDOT",
        "bid_type": "ROAD",
        "county": "Snohomish",
        "estimator": "Jane",
        "vancon": 100.0,
        "low": 100.0,
        "high": 150.0,
        "rank": 1,
        "number_bidders": 1,
        "lost_by": 0.0,
        "percent_over": 0.0,
        "won": 100.0,
        # Risk flag to test frequency insight.
        "deep": 1.0,
    },
    # WON / WINNER / TYPICAL
    {
        "job": "Bravo Bridge",
        "bid_date": datetime(2025, 2, 1),
        "was_bid": True,
        "owner": "WSDOT",
        "bid_type": "BRIDGE",
        "county": "King",
        "estimator": "Jane",
        "vancon": 200.0,
        "low": 200.0,
        "high": 260.0,
        "rank": 1,
        "number_bidders": 5,
        "lost_by": 0.0,
        "percent_over": 0.0,
        "won": 200.0,
        "traffic_control": 1.0,
    },
    # LOST / CLOSE / LIGHT
    {
        "job": "Charlie Culvert",
        "bid_date": datetime(2025, 3, 1),
        "was_bid": True,
        "owner": "City of Seattle",
        "bid_type": "WWTP",
        "county": "King",
        "estimator": "John",
        "vancon": 103.0,
        "low": 100.0,
        "high": 120.0,
        "rank": 2,
        "number_bidders": 2,
        "lost_by": 3.0,
        "percent_over": 0.03,
    },
    # LOST / MODERATE / LIGHT
    {
        "job": "Delta Drain",
        "bid_date": datetime(2025, 4, 1),
        "was_bid": True,
        "owner": "City of Seattle",
        "bid_type": "WWTP",
        "county": "King",
        "estimator": "John",
        "vancon": 108.0,
        "low": 100.0,
        "high": 130.0,
        "rank": 3,
        "number_bidders": 3,
        "lost_by": 8.0,
        "percent_over": 0.08,
    },
    # LOST / WIDE / CROWDED
    {
        "job": "Echo Ease",
        "bid_date": datetime(2025, 5, 1),
        "was_bid": True,
        "owner": "County",
        "bid_type": "ROAD",
        "county": "Snohomish",
        "estimator": "John",
        "vancon": 150.0,
        "low": 100.0,
        "high": 160.0,
        "rank": 4,
        "number_bidders": 8,
        "lost_by": 50.0,
        "percent_over": 0.5,
    },
    # NO_BID — walked away.
    {
        "job": "Foxtrot Flyover",
        "bid_date": datetime(2025, 6, 1),
        "was_bid": False,
        "owner": "WSDOT",
        "bid_type": "BRIDGE",
        "county": "Pierce",
        "estimator": "Jane",
    },
    # UNKNOWN outcome (was_bid=True, rank=None).
    {
        "job": "Golf Gap",
        "bid_date": datetime(2025, 7, 1),
        "was_bid": True,
        "owner": "County",
        "bid_type": "ROAD",
        "county": "Pierce",
        "estimator": "Jane",
        "vancon": 100.0,
        "low": 100.0,
        "rank": None,
    },
    # LOST with null ``low`` → UNKNOWN margin.
    {
        "job": "Hotel Hill",
        "bid_date": datetime(2025, 8, 1),
        "was_bid": True,
        "owner": "City of Bellevue",
        "bid_type": "WWTP",
        "county": "King",
        "estimator": "Jane",
        "vancon": 100.0,
        "low": None,
        "rank": 2,
        "number_bidders": 4,
    },
]


OUTLOOK_SEEDS: list[dict] = [
    {
        "job": "Pipeline Job 1",
        "owner": "WSDOT",
        "bid_type": "ROAD",
    },
    {
        "job": "Pipeline Job 2",
        "owner": "County",
        "bid_type": "BRIDGE",
    },
]


# Build INSERT statement dynamically from the union of keys across seeds.
_ALL_KEYS: list[str] = []
_seen: set[str] = set()
for _row in SEEDS:
    for _k in _row.keys():
        if _k not in _seen:
            _seen.add(_k)
            _ALL_KEYS.append(_k)


def _insert_sql(keys: list[str]) -> text:
    cols = ["tenant_id"] + keys
    col_sql = ", ".join(cols)
    val_sql = ", ".join(f":{c}" for c in cols)
    return text(
        f"INSERT INTO mart_bids_history ({col_sql}) VALUES ({val_sql})"
    )


OUTLOOK_INSERT_SQL = text(
    "INSERT INTO mart_bids_outlook (tenant_id, job, owner, bid_type) "
    "VALUES (:tenant_id, :job, :owner, :bid_type)"
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def seeded_engine(tmp_path) -> Engine:
    url = f"sqlite:///{tmp_path / 'bids_test.db'}"
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
        for row in SEEDS:
            # Fill in missing keys with None so the dynamic INSERT binds.
            payload = {k: row.get(k) for k in _ALL_KEYS}
            payload["tenant_id"] = tenant_id
            conn.execute(_insert_sql(_ALL_KEYS), payload)
        for row in OUTLOOK_SEEDS:
            conn.execute(
                OUTLOOK_INSERT_SQL, {"tenant_id": tenant_id, **row}
            )

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
    app.include_router(bids_router, prefix="/api/bids")

    app.dependency_overrides[get_engine] = lambda: seeded_engine
    app.dependency_overrides[get_tenant_id] = lambda: seeded_tenant_id

    _default_engine.cache_clear()

    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# Pure helpers                                                                #
# --------------------------------------------------------------------------- #


class TestBidId:
    def test_stable_for_same_input(self):
        d = datetime(2025, 1, 1)
        assert _bid_id("Alpha", d) == _bid_id("Alpha", d)

    def test_different_for_different_jobs(self):
        d = datetime(2025, 1, 1)
        assert _bid_id("Alpha", d) != _bid_id("Bravo", d)

    def test_different_for_different_dates(self):
        assert (
            _bid_id("Alpha", datetime(2025, 1, 1))
            != _bid_id("Alpha", datetime(2025, 2, 1))
        )

    def test_12_hex_chars(self):
        out = _bid_id("Alpha", datetime(2025, 1, 1))
        assert len(out) == 12
        int(out, 16)  # is valid hex

    def test_none_job_allowed(self):
        out = _bid_id(None, datetime(2025, 1, 1))
        assert len(out) == 12


class TestToBool:
    def test_bools(self):
        assert _to_bool(True) is True
        assert _to_bool(False) is False

    def test_ints(self):
        assert _to_bool(1) is True
        assert _to_bool(0) is False

    def test_floats(self):
        assert _to_bool(1.0) is True
        assert _to_bool(0.0) is False

    def test_none(self):
        assert _to_bool(None) is None

    def test_bad_type(self):
        assert _to_bool("yes") is None


class TestTruthyFlag:
    def test_one(self):
        assert _truthy_flag(1.0) is True

    def test_zero(self):
        assert _truthy_flag(0.0) is False

    def test_none(self):
        assert _truthy_flag(None) is False

    def test_bad_value(self):
        assert _truthy_flag("nope") is False


class TestPercentOver:
    def test_basic(self):
        assert _percent_over(110.0, 100.0) == pytest.approx(0.10)

    def test_zero_when_equal(self):
        assert _percent_over(100.0, 100.0) == 0.0

    def test_none_when_low_zero(self):
        assert _percent_over(100.0, 0.0) is None

    def test_none_when_any_null(self):
        assert _percent_over(None, 100.0) is None
        assert _percent_over(100.0, None) is None


class TestOutcomeHelper:
    def test_no_bid(self):
        assert _outcome(False, 1) is BidOutcome.NO_BID

    def test_won(self):
        assert _outcome(True, 1) is BidOutcome.WON

    def test_lost(self):
        assert _outcome(True, 2) is BidOutcome.LOST

    def test_unknown_when_null_rank(self):
        assert _outcome(True, None) is BidOutcome.UNKNOWN

    def test_handles_float_rank(self):
        assert _outcome(True, 1.0) is BidOutcome.WON
        assert _outcome(True, 3.0) is BidOutcome.LOST


class TestMarginTierHelper:
    def test_winner_short_circuits(self):
        # WON outcome is WINNER regardless of percent_over value.
        assert (
            _margin_tier(BidOutcome.WON, None, close_max=0.03, moderate_max=0.10)
            is MarginTier.WINNER
        )

    def test_close(self):
        assert (
            _margin_tier(BidOutcome.LOST, 0.02, close_max=0.03, moderate_max=0.10)
            is MarginTier.CLOSE
        )

    def test_moderate(self):
        assert (
            _margin_tier(BidOutcome.LOST, 0.07, close_max=0.03, moderate_max=0.10)
            is MarginTier.MODERATE
        )

    def test_wide(self):
        assert (
            _margin_tier(BidOutcome.LOST, 0.5, close_max=0.03, moderate_max=0.10)
            is MarginTier.WIDE
        )

    def test_unknown_when_null(self):
        assert (
            _margin_tier(BidOutcome.LOST, None, close_max=0.03, moderate_max=0.10)
            is MarginTier.UNKNOWN
        )


class TestCompetitionTierHelper:
    def test_solo(self):
        assert _competition_tier(1, light_max=3, typical_max=6) is CompetitionTier.SOLO

    def test_light(self):
        assert _competition_tier(3, light_max=3, typical_max=6) is CompetitionTier.LIGHT

    def test_typical(self):
        assert _competition_tier(5, light_max=3, typical_max=6) is CompetitionTier.TYPICAL

    def test_crowded(self):
        assert _competition_tier(9, light_max=3, typical_max=6) is CompetitionTier.CROWDED

    def test_unknown_for_null(self):
        assert _competition_tier(None, light_max=3, typical_max=6) is CompetitionTier.UNKNOWN

    def test_unknown_for_zero(self):
        assert _competition_tier(0, light_max=3, typical_max=6) is CompetitionTier.UNKNOWN


# --------------------------------------------------------------------------- #
# /summary                                                                    #
# --------------------------------------------------------------------------- #


class TestSummary:
    def test_totals(self, client: TestClient):
        resp = client.get("/api/bids/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_bids"] == 8
        assert body["bids_submitted"] == 7
        assert body["no_bids"] == 1

    def test_outcome_counts(self, client: TestClient):
        body = client.get("/api/bids/summary").json()
        # 2 wins (Alpha, Bravo), 4 losses (Charlie, Delta, Echo, Hotel),
        # 1 unknown (Golf).
        assert body["bids_won"] == 2
        assert body["bids_lost"] == 4
        assert body["unknown_outcome"] == 1

    def test_win_rate(self, client: TestClient):
        body = client.get("/api/bids/summary").json()
        # 2 wins / 7 submitted = 0.2857
        assert body["win_rate"] == pytest.approx(2 / 7, rel=1e-3)

    def test_dollar_totals(self, client: TestClient):
        body = client.get("/api/bids/summary").json()
        # Sum of vancon on all 7 submitted: 100+200+103+108+150+100+100=861
        assert body["total_vancon_bid_amount"] == pytest.approx(861.0)
        # Sum on wins only: 100+200 = 300
        assert body["total_vancon_won_amount"] == pytest.approx(300.0)
        # Avg: 861 / 7 ~= 123.0
        assert body["avg_vancon_bid"] == pytest.approx(861.0 / 7, rel=1e-3)

    def test_median_bidders(self, client: TestClient):
        body = client.get("/api/bids/summary").json()
        # Submitted bidder counts: 1, 5, 2, 3, 8, 4 → median=3.5
        assert body["median_number_bidders"] == pytest.approx(3.5)

    def test_distinct_counts(self, client: TestClient):
        body = client.get("/api/bids/summary").json()
        # estimators: Jane, John = 2
        assert body["distinct_estimators"] == 2
        # owners: WSDOT, City of Seattle, County, City of Bellevue = 4
        assert body["distinct_owners"] == 4
        # counties: Snohomish, King, Pierce = 3
        assert body["distinct_counties"] == 3
        # bid_types: ROAD, BRIDGE, WWTP = 3
        assert body["distinct_bid_types"] == 3

    def test_outlook_count(self, client: TestClient):
        body = client.get("/api/bids/summary").json()
        # Seeded 2 outlook rows.
        assert body["outlook_count"] == 2


# --------------------------------------------------------------------------- #
# /list                                                                       #
# --------------------------------------------------------------------------- #


class TestList:
    def test_default_pagination(self, client: TestClient):
        body = client.get("/api/bids/list").json()
        assert body["total"] == 8
        assert body["page"] == 1
        assert body["page_size"] == 25
        assert len(body["items"]) == 8

    def test_sort_by_bid_date_desc_default(self, client: TestClient):
        body = client.get("/api/bids/list").json()
        jobs = [r["job"] for r in body["items"]]
        # Hotel (Aug) first, then Golf (Jul), Fox (Jun), etc.
        assert jobs[0] == "Hotel Hill"
        assert jobs[-1] == "Alpha Tunnel"

    def test_sort_by_job_asc(self, client: TestClient):
        body = client.get("/api/bids/list?sort_by=job&sort_dir=asc").json()
        jobs = [r["job"] for r in body["items"]]
        assert jobs == sorted(jobs, key=str.lower)

    def test_sort_nulls_last_percent_over_desc(self, client: TestClient):
        body = client.get(
            "/api/bids/list?sort_by=percent_over&sort_dir=desc"
        ).json()
        items = body["items"]
        # Hotel Hill has low=None → percent_over=None, should be last.
        assert items[-1]["job"] == "Hotel Hill"
        # Echo Ease 0.50 is the max → first.
        assert items[0]["job"] == "Echo Ease"

    def test_pagination(self, client: TestClient):
        body = client.get("/api/bids/list?page=1&page_size=3").json()
        assert body["page"] == 1
        assert body["page_size"] == 3
        assert len(body["items"]) == 3
        body2 = client.get("/api/bids/list?page=2&page_size=3").json()
        assert len(body2["items"]) == 3
        body3 = client.get("/api/bids/list?page=3&page_size=3").json()
        assert len(body3["items"]) == 2  # 8 total

    def test_filter_outcome_won(self, client: TestClient):
        body = client.get("/api/bids/list?outcome=won").json()
        assert body["total"] == 2
        assert {r["job"] for r in body["items"]} == {"Alpha Tunnel", "Bravo Bridge"}

    def test_filter_outcome_lost(self, client: TestClient):
        body = client.get("/api/bids/list?outcome=lost").json()
        assert body["total"] == 4

    def test_filter_outcome_no_bid(self, client: TestClient):
        body = client.get("/api/bids/list?outcome=no_bid").json()
        assert body["total"] == 1
        assert body["items"][0]["job"] == "Foxtrot Flyover"

    def test_filter_outcome_unknown(self, client: TestClient):
        body = client.get("/api/bids/list?outcome=unknown").json()
        assert body["total"] == 1
        assert body["items"][0]["job"] == "Golf Gap"

    def test_filter_margin_close(self, client: TestClient):
        body = client.get("/api/bids/list?margin_tier=close").json()
        assert body["total"] == 1
        assert body["items"][0]["job"] == "Charlie Culvert"

    def test_filter_margin_moderate(self, client: TestClient):
        body = client.get("/api/bids/list?margin_tier=moderate").json()
        assert body["total"] == 1
        assert body["items"][0]["job"] == "Delta Drain"

    def test_filter_margin_wide(self, client: TestClient):
        body = client.get("/api/bids/list?margin_tier=wide").json()
        assert body["total"] == 1
        assert body["items"][0]["job"] == "Echo Ease"

    def test_filter_margin_winner(self, client: TestClient):
        body = client.get("/api/bids/list?margin_tier=winner").json()
        assert body["total"] == 2

    def test_filter_competition_solo(self, client: TestClient):
        body = client.get("/api/bids/list?competition_tier=solo").json()
        assert body["total"] == 1
        assert body["items"][0]["job"] == "Alpha Tunnel"

    def test_filter_competition_light(self, client: TestClient):
        body = client.get("/api/bids/list?competition_tier=light").json()
        # Charlie (2), Delta (3)
        assert body["total"] == 2

    def test_filter_competition_typical(self, client: TestClient):
        body = client.get("/api/bids/list?competition_tier=typical").json()
        # Bravo (5), Hotel (4)
        assert body["total"] == 2

    def test_filter_competition_crowded(self, client: TestClient):
        body = client.get("/api/bids/list?competition_tier=crowded").json()
        assert body["total"] == 1
        assert body["items"][0]["job"] == "Echo Ease"

    def test_filter_bid_type(self, client: TestClient):
        body = client.get("/api/bids/list?bid_type=WWTP").json()
        assert body["total"] == 3  # Charlie, Delta, Hotel

    def test_filter_estimator(self, client: TestClient):
        body = client.get("/api/bids/list?estimator=John").json()
        assert body["total"] == 3  # Charlie, Delta, Echo

    def test_filter_county(self, client: TestClient):
        body = client.get("/api/bids/list?county=King").json()
        assert body["total"] == 4  # Bravo, Charlie, Delta, Hotel

    def test_search_substring(self, client: TestClient):
        body = client.get("/api/bids/list?search=tunnel").json()
        assert body["total"] == 1
        assert body["items"][0]["job"] == "Alpha Tunnel"

    def test_search_case_insensitive(self, client: TestClient):
        body = client.get("/api/bids/list?search=BRAVO").json()
        assert body["total"] == 1
        assert body["items"][0]["job"] == "Bravo Bridge"

    def test_custom_margin_thresholds(self, client: TestClient):
        # Widen close_max to 10% → Delta (8%) becomes CLOSE.
        body = client.get(
            "/api/bids/list?margin_tier=close&close_max=0.10&moderate_max=0.30"
        ).json()
        jobs = {r["job"] for r in body["items"]}
        assert "Charlie Culvert" in jobs
        assert "Delta Drain" in jobs

    def test_custom_competition_thresholds(self, client: TestClient):
        # light_max=5 → Bravo (5) becomes LIGHT.
        body = client.get(
            "/api/bids/list?competition_tier=light&light_max=5&typical_max=7"
        ).json()
        jobs = {r["job"] for r in body["items"]}
        assert "Bravo Bridge" in jobs
        # Charlie (2) and Delta (3) are still LIGHT under the wider band too.
        assert "Charlie Culvert" in jobs
        assert "Delta Drain" in jobs


# --------------------------------------------------------------------------- #
# /{bid_id}                                                                   #
# --------------------------------------------------------------------------- #


class TestDetail:
    def _bid_id(self, job: str, bid_date: datetime) -> str:
        return _bid_id(job, bid_date)

    def test_404_for_missing(self, client: TestClient):
        resp = client.get("/api/bids/deadbeefdead")
        assert resp.status_code == 404

    def test_404_for_empty(self, client: TestClient):
        # FastAPI catches the truly empty path; sending an obviously bad
        # id confirms the service's own None-return path.
        resp = client.get("/api/bids/xxx")
        assert resp.status_code == 404

    def test_fetches_alpha_tunnel(self, client: TestClient):
        bid_id = self._bid_id("Alpha Tunnel", datetime(2025, 1, 1))
        resp = client.get(f"/api/bids/{bid_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == bid_id
        assert body["job"] == "Alpha Tunnel"
        assert body["outcome"] == "won"
        assert body["margin_tier"] == "winner"
        assert body["competition_tier"] == "solo"
        assert body["was_bid"] is True
        assert body["vancon"] == 100.0
        assert body["low"] == 100.0
        assert body["rank"] == 1
        assert body["estimator"] == "Jane"

    def test_detail_exposes_risk_flags(self, client: TestClient):
        bid_id = self._bid_id("Alpha Tunnel", datetime(2025, 1, 1))
        body = client.get(f"/api/bids/{bid_id}").json()
        assert "deep" in body["risk_flags"]

    def test_detail_no_bid_fields(self, client: TestClient):
        bid_id = self._bid_id("Foxtrot Flyover", datetime(2025, 6, 1))
        body = client.get(f"/api/bids/{bid_id}").json()
        assert body["outcome"] == "no_bid"
        assert body["was_bid"] is False
        assert body["vancon"] is None

    def test_detail_unknown_outcome(self, client: TestClient):
        bid_id = self._bid_id("Golf Gap", datetime(2025, 7, 1))
        body = client.get(f"/api/bids/{bid_id}").json()
        assert body["outcome"] == "unknown"

    def test_detail_competitors_empty(self, client: TestClient):
        # We did not seed any bid_{i}_comp columns.
        bid_id = self._bid_id("Alpha Tunnel", datetime(2025, 1, 1))
        body = client.get(f"/api/bids/{bid_id}").json()
        assert body["competitors"] == []


# --------------------------------------------------------------------------- #
# /insights                                                                   #
# --------------------------------------------------------------------------- #


class TestInsights:
    def test_outcome_breakdown(self, client: TestClient):
        body = client.get("/api/bids/insights").json()
        ob = body["outcome_breakdown"]
        assert ob["won"] == 2
        assert ob["lost"] == 4
        assert ob["no_bid"] == 1
        assert ob["unknown"] == 1

    def test_margin_breakdown(self, client: TestClient):
        body = client.get("/api/bids/insights").json()
        mb = body["margin_tier_breakdown"]
        assert mb["winner"] == 2
        assert mb["close"] == 1
        assert mb["moderate"] == 1
        assert mb["wide"] == 1
        # Hotel Hill (null low) and Golf Gap (unknown outcome, no rank)
        # both end up UNKNOWN inside the submitted-only slice.
        assert mb["unknown"] == 2

    def test_competition_breakdown(self, client: TestClient):
        body = client.get("/api/bids/insights").json()
        cb = body["competition_tier_breakdown"]
        assert cb["solo"] == 1        # Alpha
        assert cb["light"] == 2       # Charlie, Delta
        assert cb["typical"] == 2     # Bravo, Hotel
        assert cb["crowded"] == 1     # Echo
        assert cb["unknown"] == 1     # Golf

    def test_win_rate_by_bid_type(self, client: TestClient):
        body = client.get("/api/bids/insights").json()
        rows = {r["segment"]: r for r in body["win_rate_by_bid_type"]}
        # WWTP: 3 submissions, 0 wins.
        assert rows["WWTP"]["submitted"] == 3
        assert rows["WWTP"]["won"] == 0
        assert rows["WWTP"]["win_rate"] == 0.0
        # ROAD: Alpha (win), Echo (loss), Golf (unknown) = 3 submissions, 1 win.
        assert rows["ROAD"]["submitted"] == 3
        assert rows["ROAD"]["won"] == 1
        # BRIDGE: Bravo (win) only — Foxtrot was NO_BID so it doesn't count.
        assert rows["BRIDGE"]["submitted"] == 1
        assert rows["BRIDGE"]["won"] == 1

    def test_win_rate_by_estimator(self, client: TestClient):
        body = client.get("/api/bids/insights").json()
        rows = {r["segment"]: r for r in body["win_rate_by_estimator"]}
        # Jane: Alpha (win), Bravo (win), Golf (unknown), Hotel (loss) = 4 submitted, 2 won.
        assert rows["Jane"]["submitted"] == 4
        assert rows["Jane"]["won"] == 2
        assert rows["Jane"]["win_rate"] == pytest.approx(0.5)
        # John: Charlie, Delta, Echo — all losses.
        assert rows["John"]["submitted"] == 3
        assert rows["John"]["won"] == 0

    def test_near_misses_sorted_ascending(self, client: TestClient):
        body = client.get("/api/bids/insights").json()
        nm = body["near_misses"]
        # Charlie (3), Delta (8), Echo (50). Hotel has lost_by=None so skipped.
        assert [r["job"] for r in nm[:3]] == [
            "Charlie Culvert", "Delta Drain", "Echo Ease",
        ]

    def test_big_wins(self, client: TestClient):
        body = client.get("/api/bids/insights").json()
        bw = body["big_wins"]
        # Bravo (200) > Alpha (100).
        assert bw[0]["job"] == "Bravo Bridge"
        assert bw[0]["vancon"] == 200.0
        assert bw[1]["job"] == "Alpha Tunnel"

    def test_risk_flag_frequency(self, client: TestClient):
        body = client.get("/api/bids/insights").json()
        rows = {r["flag"]: r for r in body["risk_flag_frequency"]}
        # Alpha has `deep` = 1.0; Bravo has `traffic_control` = 1.0.
        assert rows["deep"]["count"] == 1
        assert rows["deep"]["win_rate"] == 1.0  # Alpha won.
        assert rows["traffic_control"]["count"] == 1
        assert rows["traffic_control"]["win_rate"] == 1.0  # Bravo won.
        # Other flags → 0 count, 0 win_rate.
        assert rows["dewatering"]["count"] == 0

    def test_top_n_limit(self, client: TestClient):
        body = client.get("/api/bids/insights?top_n=1").json()
        assert len(body["win_rate_by_bid_type"]) == 1
        assert len(body["win_rate_by_estimator"]) == 1
        assert len(body["near_misses"]) == 1
        assert len(body["big_wins"]) == 1


# --------------------------------------------------------------------------- #
# Cross-cutting                                                               #
# --------------------------------------------------------------------------- #


class TestEmptyTenant:
    def test_summary_empty(self, seeded_engine: Engine):
        """A fresh tenant with no bid rows still gets a well-shaped summary."""
        # Insert a second tenant with nothing seeded.
        empty_id = str(uuid.uuid4())
        with sessionmaker(seeded_engine)() as s:
            s.add(
                Tenant(
                    id=empty_id,
                    slug="empty",
                    company_name="Empty Co.",
                    contact_email="admin@empty.test",
                    tier=SubscriptionTier.STARTER,
                    status=TenantStatus.ACTIVE,
                )
            )
            s.commit()

        app = FastAPI()
        app.include_router(bids_router, prefix="/api/bids")
        app.dependency_overrides[get_engine] = lambda: seeded_engine
        app.dependency_overrides[get_tenant_id] = lambda: empty_id
        _default_engine.cache_clear()

        with TestClient(app) as c:
            body = c.get("/api/bids/summary").json()

        assert body["total_bids"] == 0
        assert body["bids_submitted"] == 0
        assert body["win_rate"] == 0.0
        assert body["median_number_bidders"] is None

    def test_insights_empty(self, seeded_engine: Engine):
        empty_id = str(uuid.uuid4())
        with sessionmaker(seeded_engine)() as s:
            s.add(
                Tenant(
                    id=empty_id,
                    slug="empty2",
                    company_name="Empty2 Co.",
                    contact_email="admin@empty2.test",
                    tier=SubscriptionTier.STARTER,
                    status=TenantStatus.ACTIVE,
                )
            )
            s.commit()

        app = FastAPI()
        app.include_router(bids_router, prefix="/api/bids")
        app.dependency_overrides[get_engine] = lambda: seeded_engine
        app.dependency_overrides[get_tenant_id] = lambda: empty_id
        _default_engine.cache_clear()

        with TestClient(app) as c:
            body = c.get("/api/bids/insights").json()

        assert body["outcome_breakdown"] == {
            "won": 0, "lost": 0, "no_bid": 0, "unknown": 0,
        }
        assert body["near_misses"] == []
        assert body["big_wins"] == []
