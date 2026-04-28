"""Tests for app.modules.cost_coding.

Strategy mirrors the other mart-backed modules:
  1. Fresh SQLite DB per test via fixtures.
  2. Register every mart Table against Base.metadata, create_all().
  3. Seed a small, canonical set of activity-code rows that spans
     every cost category, size tier, and usage tier with tight
     threshold overrides so the buckets are reachable.
  4. Drive the API through TestClient with dependency overrides.

Canonical seed — five activity codes across multiple estimates:

  Code        Estimates  Labor   PermMat  ConstMat  Equip    Sub      Notes
  1101.100    3          3000    0        0         0        0        LABOR-dominant, HEAVY-ish under tight threshold
  2300.001    2          500     8000     0         0        0        PERMANENT_MATERIAL-dominant, LIGHT
  2700.150    2          0       0        0         6000     0        EQUIPMENT-dominant, LIGHT
  9500.900    1          200     300      100       250      250      MIXED (no bucket >= 60%), SINGLETON
  9999.ZERO   2          0       0        0         0        0        ZERO category, LIGHT

Thresholds used throughout the tests:
  category_dominance=0.6, major_cost_min=5000, significant_cost_min=1000,
  heavy_min=3, regular_min=2
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import sessionmaker

# Register every mart Table against Base.metadata.
import app.services.excel_marts  # noqa: F401
from app.core.database import Base
from app.models.tenant import SubscriptionTier, Tenant, TenantStatus
from app.modules.cost_coding.router import (
    _default_engine,
    get_engine,
    get_tenant_id,
    router as cost_coding_router,
)
from app.modules.cost_coding.service import (
    _cost_category,
    _major_code,
    _norm_code,
    _size_tier,
    _usage_tier,
)


# --------------------------------------------------------------------------- #
# Test thresholds                                                             #
# --------------------------------------------------------------------------- #


CATEGORY_DOMINANCE = 0.6
MAJOR_COST_MIN = 5_000.0
SIGNIFICANT_COST_MIN = 1_000.0
HEAVY_MIN = 3
REGULAR_MIN = 2

THRESHOLD_QS = (
    f"category_dominance={CATEGORY_DOMINANCE}"
    f"&major_cost_min={MAJOR_COST_MIN}"
    f"&significant_cost_min={SIGNIFICANT_COST_MIN}"
    f"&heavy_min={HEAVY_MIN}"
    f"&regular_min={REGULAR_MIN}"
)


# --------------------------------------------------------------------------- #
# Canonical seed                                                              #
# --------------------------------------------------------------------------- #


SEEDS: list[dict] = [
    # 1101.100 — LABOR-dominant, 3 estimates → HEAVY usage under (3,2)
    {
        "estimate_code": "EST-A",
        "activity_code": "1101.100",
        "estimate_name": "Alpha Job",
        "activity_description": "Labor foreman",
        "man_hours": 40.0,
        "direct_total_cost": 1000.0,
        "labor_cost": 1000.0,
        "permanent_material_cost": None,
        "construction_material_cost": None,
        "equipment_cost": None,
        "subcontract_cost": None,
    },
    {
        "estimate_code": "EST-B",
        "activity_code": "1101.100",
        "estimate_name": "Bravo Job",
        "activity_description": "Labor foreman",
        "man_hours": 50.0,
        "direct_total_cost": 1200.0,
        "labor_cost": 1200.0,
        "permanent_material_cost": None,
        "construction_material_cost": None,
        "equipment_cost": None,
        "subcontract_cost": None,
    },
    {
        "estimate_code": "EST-C",
        "activity_code": "1101.100",
        "estimate_name": "Charlie Job",
        # Different description on purpose (drift test)
        "activity_description": "Labor crew",
        "man_hours": 30.0,
        "direct_total_cost": 800.0,
        "labor_cost": 800.0,
        "permanent_material_cost": None,
        "construction_material_cost": None,
        "equipment_cost": None,
        "subcontract_cost": None,
    },

    # 2300.001 — PERMANENT_MATERIAL-dominant ($500 labor + $8000 mat), 2 estimates → LIGHT
    {
        "estimate_code": "EST-A",
        "activity_code": "2300.001",
        "estimate_name": "Alpha Job",
        "activity_description": "Concrete pour",
        "man_hours": 5.0,
        "direct_total_cost": 4500.0,
        "labor_cost": 300.0,
        "permanent_material_cost": 4000.0,
        "construction_material_cost": None,
        "equipment_cost": None,
        "subcontract_cost": None,
    },
    {
        "estimate_code": "EST-B",
        "activity_code": "2300.001",
        "estimate_name": "Bravo Job",
        "activity_description": "Concrete pour",
        "man_hours": 3.0,
        "direct_total_cost": 4200.0,
        "labor_cost": 200.0,
        "permanent_material_cost": 4000.0,
        "construction_material_cost": None,
        "equipment_cost": None,
        "subcontract_cost": None,
    },

    # 2700.150 — EQUIPMENT-dominant, 2 estimates → LIGHT
    {
        "estimate_code": "EST-A",
        "activity_code": "2700.150",
        "estimate_name": "Alpha Job",
        "activity_description": "Excavator rental",
        "man_hours": 10.0,
        "direct_total_cost": 3000.0,
        "labor_cost": None,
        "permanent_material_cost": None,
        "construction_material_cost": None,
        "equipment_cost": 3000.0,
        "subcontract_cost": None,
    },
    {
        "estimate_code": "EST-D",
        "activity_code": "2700.150",
        "estimate_name": "Delta Job",
        "activity_description": "Excavator rental",
        "man_hours": 10.0,
        "direct_total_cost": 3000.0,
        "labor_cost": None,
        "permanent_material_cost": None,
        "construction_material_cost": None,
        "equipment_cost": 3000.0,
        "subcontract_cost": None,
    },

    # 9500.900 — MIXED (no bucket >= 60%), 1 estimate → SINGLETON
    {
        "estimate_code": "EST-E",
        "activity_code": "9500.900",
        "estimate_name": "Echo Job",
        "activity_description": "General overhead",
        "man_hours": 2.0,
        "direct_total_cost": 1100.0,
        "labor_cost": 200.0,
        "permanent_material_cost": 300.0,
        "construction_material_cost": 100.0,
        "equipment_cost": 250.0,
        "subcontract_cost": 250.0,
    },

    # 9999.ZERO — ZERO category, 2 estimates → LIGHT usage, ZERO size tier
    {
        "estimate_code": "EST-A",
        "activity_code": "9999.ZERO",
        "estimate_name": "Alpha Job",
        "activity_description": "Placeholder unused",
        "man_hours": 0.0,
        "direct_total_cost": 0.0,
        "labor_cost": None,
        "permanent_material_cost": None,
        "construction_material_cost": None,
        "equipment_cost": None,
        "subcontract_cost": None,
    },
    {
        "estimate_code": "EST-F",
        "activity_code": "9999.ZERO",
        "estimate_name": "Foxtrot Job",
        "activity_description": "Placeholder unused",
        "man_hours": 0.0,
        "direct_total_cost": 0.0,
        "labor_cost": None,
        "permanent_material_cost": None,
        "construction_material_cost": None,
        "equipment_cost": None,
        "subcontract_cost": None,
    },
]


INSERT_SQL = text(
    """
    INSERT INTO mart_hcss_activities
        (tenant_id, estimate_code, activity_code, estimate_name,
         activity_description, man_hours, direct_total_cost, labor_cost,
         permanent_material_cost, construction_material_cost,
         equipment_cost, subcontract_cost)
    VALUES
        (:tenant_id, :estimate_code, :activity_code, :estimate_name,
         :activity_description, :man_hours, :direct_total_cost, :labor_cost,
         :permanent_material_cost, :construction_material_cost,
         :equipment_cost, :subcontract_cost)
    """
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def seeded_engine(tmp_path) -> Engine:
    url = f"sqlite:///{tmp_path / 'cost_coding_test.db'}"
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
            conn.execute(INSERT_SQL, {"tenant_id": tenant_id, **row})

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
    app.include_router(cost_coding_router, prefix="/api/cost-coding")

    app.dependency_overrides[get_engine] = lambda: seeded_engine
    app.dependency_overrides[get_tenant_id] = lambda: seeded_tenant_id

    _default_engine.cache_clear()

    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# Pure helpers                                                                #
# --------------------------------------------------------------------------- #


class TestNormCode:
    def test_strips(self):
        assert _norm_code("  1101.100 ") == "1101.100"

    def test_none_returns_none(self):
        assert _norm_code(None) is None

    def test_empty_returns_none(self):
        assert _norm_code("   ") is None


class TestMajorCode:
    def test_pre_dot(self):
        assert _major_code("1101.100") == "1101"
        assert _major_code("900.9010") == "900"

    def test_no_dot(self):
        assert _major_code("02300") == "02300"

    def test_leading_dot_is_none(self):
        assert _major_code(".1") is None

    def test_empty_and_none(self):
        assert _major_code(None) is None
        assert _major_code("") is None


class TestCostCategoryHelper:
    def test_labor_dominant(self):
        assert _cost_category(1000, 0, 0, 0, 0).value == "labor"

    def test_mixed_when_no_dominant(self):
        assert _cost_category(200, 300, 100, 250, 250).value == "mixed"

    def test_zero_when_no_cost(self):
        assert _cost_category(0, 0, 0, 0, 0).value == "zero"

    def test_equipment_dominant(self):
        assert _cost_category(0, 0, 0, 5000, 0).value == "equipment"


class TestSizeTierHelper:
    def test_thresholds(self):
        assert _size_tier(10_000, major_min=5_000, significant_min=1_000).value == "major"
        assert _size_tier(2_000, major_min=5_000, significant_min=1_000).value == "significant"
        assert _size_tier(500, major_min=5_000, significant_min=1_000).value == "minor"
        assert _size_tier(0, major_min=5_000, significant_min=1_000).value == "zero"


class TestUsageTierHelper:
    def test_thresholds(self):
        assert _usage_tier(5, heavy_min=3, regular_min=2).value == "heavy"
        assert _usage_tier(2, heavy_min=3, regular_min=2).value == "regular"
        # light kicks in only when regular_min > 2
        assert _usage_tier(2, heavy_min=5, regular_min=3).value == "light"
        assert _usage_tier(1, heavy_min=3, regular_min=2).value == "singleton"


# --------------------------------------------------------------------------- #
# /summary                                                                    #
# --------------------------------------------------------------------------- #


class TestSummary:
    def test_totals(self, client: TestClient):
        resp = client.get("/api/cost-coding/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_codes"] == 5
        assert body["total_activities"] == 10  # total seeded rows
        # Distinct estimates: A, B, C, D, E, F = 6
        assert body["distinct_estimates"] == 6

    def test_cost_totals(self, client: TestClient):
        body = client.get("/api/cost-coding/summary").json()
        # Labor: 1000+1200+800 + 300+200 + 200 = 3700
        assert body["total_labor_cost"] == 3700.0
        # Perm material: 4000+4000 + 300 = 8300
        assert body["total_permanent_material_cost"] == 8300.0
        # Construction material: 100
        assert body["total_construction_material_cost"] == 100.0
        # Equipment: 3000+3000 + 250 = 6250
        assert body["total_equipment_cost"] == 6250.0
        # Subcontract: 250
        assert body["total_subcontract_cost"] == 250.0
        # Direct cost sum: 1000+1200+800+4500+4200+3000+3000+1100 = 18800
        assert body["total_direct_cost"] == 18800.0
        # Man-hours: 40+50+30+5+3+10+10+2 = 150
        assert body["total_man_hours"] == 150.0

    def test_coverage_counts(self, client: TestClient):
        body = client.get("/api/cost-coding/summary").json()
        # Codes with labor > 0: 1101.100, 2300.001, 9500.900 = 3
        assert body["codes_with_labor"] == 3
        # Codes with perm_material > 0: 2300.001, 9500.900 = 2
        assert body["codes_with_permanent_material"] == 2
        # Codes with construction_material > 0: 9500.900 = 1
        assert body["codes_with_construction_material"] == 1
        # Codes with equipment > 0: 2700.150, 9500.900 = 2
        assert body["codes_with_equipment"] == 2
        # Codes with subcontract > 0: 9500.900 = 1
        assert body["codes_with_subcontract"] == 1
        # Uncosted codes: just 9999.ZERO
        assert body["uncosted_codes"] == 1


# --------------------------------------------------------------------------- #
# /list                                                                       #
# --------------------------------------------------------------------------- #


class TestList:
    def test_default_pagination(self, client: TestClient):
        body = client.get(f"/api/cost-coding/list?{THRESHOLD_QS}").json()
        assert body["total"] == 5
        assert body["page"] == 1
        assert body["page_size"] == 25
        assert len(body["items"]) == 5

    def test_sort_by_code_asc(self, client: TestClient):
        body = client.get(
            f"/api/cost-coding/list?sort_by=code&sort_dir=asc&{THRESHOLD_QS}"
        ).json()
        codes = [r["code"] for r in body["items"]]
        assert codes == sorted(codes, key=str.lower)

    def test_default_sort_is_cost_desc(self, client: TestClient):
        body = client.get(f"/api/cost-coding/list?{THRESHOLD_QS}").json()
        costs = [r["total_direct_cost"] for r in body["items"]]
        assert costs == sorted(costs, reverse=True)
        # Top is 2300.001 at $8700
        assert body["items"][0]["code"] == "2300.001"
        assert body["items"][0]["total_direct_cost"] == 8700.0

    def test_filter_category_labor(self, client: TestClient):
        body = client.get(
            f"/api/cost-coding/list?cost_category=labor&{THRESHOLD_QS}"
        ).json()
        assert body["total"] == 1
        assert body["items"][0]["code"] == "1101.100"

    def test_filter_category_equipment(self, client: TestClient):
        body = client.get(
            f"/api/cost-coding/list?cost_category=equipment&{THRESHOLD_QS}"
        ).json()
        assert body["total"] == 1
        assert body["items"][0]["code"] == "2700.150"

    def test_filter_category_mixed(self, client: TestClient):
        body = client.get(
            f"/api/cost-coding/list?cost_category=mixed&{THRESHOLD_QS}"
        ).json()
        assert body["total"] == 1
        assert body["items"][0]["code"] == "9500.900"

    def test_filter_category_zero(self, client: TestClient):
        body = client.get(
            f"/api/cost-coding/list?cost_category=zero&{THRESHOLD_QS}"
        ).json()
        assert body["total"] == 1
        assert body["items"][0]["code"] == "9999.ZERO"

    def test_filter_size_major(self, client: TestClient):
        # major_cost_min=5000 → 2300.001 ($8700) qualifies, 2700.150 ($6000) qualifies.
        body = client.get(
            f"/api/cost-coding/list?size_tier=major&{THRESHOLD_QS}"
        ).json()
        codes = {r["code"] for r in body["items"]}
        assert codes == {"2300.001", "2700.150"}

    def test_filter_size_significant(self, client: TestClient):
        # significant_cost_min=1000 → 1101.100 ($3000), 9500.900 ($1100).
        body = client.get(
            f"/api/cost-coding/list?size_tier=significant&{THRESHOLD_QS}"
        ).json()
        codes = {r["code"] for r in body["items"]}
        assert codes == {"1101.100", "9500.900"}

    def test_filter_usage_heavy(self, client: TestClient):
        # heavy_min=3 → 1101.100 (3 estimates).
        body = client.get(
            f"/api/cost-coding/list?usage_tier=heavy&{THRESHOLD_QS}"
        ).json()
        assert body["total"] == 1
        assert body["items"][0]["code"] == "1101.100"

    def test_filter_usage_regular(self, client: TestClient):
        # regular_min=2 and heavy_min=3 → 2 estimates → regular.
        body = client.get(
            f"/api/cost-coding/list?usage_tier=regular&{THRESHOLD_QS}"
        ).json()
        codes = {r["code"] for r in body["items"]}
        assert codes == {"2300.001", "2700.150", "9999.ZERO"}

    def test_filter_usage_singleton(self, client: TestClient):
        body = client.get(
            f"/api/cost-coding/list?usage_tier=singleton&{THRESHOLD_QS}"
        ).json()
        assert body["total"] == 1
        assert body["items"][0]["code"] == "9500.900"

    def test_filter_major_code(self, client: TestClient):
        body = client.get(
            f"/api/cost-coding/list?major_code=1101&{THRESHOLD_QS}"
        ).json()
        assert body["total"] == 1
        assert body["items"][0]["code"] == "1101.100"

    def test_search_matches_code(self, client: TestClient):
        body = client.get(
            f"/api/cost-coding/list?search=2700&{THRESHOLD_QS}"
        ).json()
        assert body["total"] == 1
        assert body["items"][0]["code"] == "2700.150"

    def test_search_matches_description(self, client: TestClient):
        body = client.get(
            f"/api/cost-coding/list?search=concrete&{THRESHOLD_QS}"
        ).json()
        assert body["total"] == 1
        assert body["items"][0]["code"] == "2300.001"

    def test_page_size_slicing(self, client: TestClient):
        body = client.get(
            f"/api/cost-coding/list?page=2&page_size=2&{THRESHOLD_QS}"
        ).json()
        assert body["total"] == 5
        assert body["page"] == 2
        assert body["page_size"] == 2
        assert len(body["items"]) == 2


# --------------------------------------------------------------------------- #
# /{code_id}                                                                  #
# --------------------------------------------------------------------------- #


class TestDetail:
    def test_fetch_by_code(self, client: TestClient):
        resp = client.get(f"/api/cost-coding/1101.100?{THRESHOLD_QS}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == "1101.100"
        assert body["major_code"] == "1101"
        assert body["cost_category"] == "labor"
        assert body["usage_tier"] == "heavy"
        assert body["estimate_count"] == 3
        # Canonical description is the most-common value — "Labor foreman"
        # appeared twice vs "Labor crew" once.
        assert body["description"] == "Labor foreman"
        # distinct_descriptions = 2
        assert body["distinct_descriptions"] == 2

    def test_detail_estimate_breakdown_ordered(self, client: TestClient):
        body = client.get(f"/api/cost-coding/1101.100?{THRESHOLD_QS}").json()
        costs = [e["direct_total_cost"] for e in body["estimates"]]
        assert costs == sorted(costs, reverse=True)
        # Top is EST-B at $1200
        assert body["estimates"][0]["estimate_code"] == "EST-B"
        assert body["estimates"][0]["direct_total_cost"] == 1200.0

    def test_detail_whitespace_tolerant(self, client: TestClient):
        resp = client.get(f"/api/cost-coding/  1101.100  ?{THRESHOLD_QS}")
        assert resp.status_code == 200
        assert resp.json()["code"] == "1101.100"

    def test_detail_mixed_code(self, client: TestClient):
        body = client.get(f"/api/cost-coding/9500.900?{THRESHOLD_QS}").json()
        assert body["cost_category"] == "mixed"
        assert body["usage_tier"] == "singleton"
        assert body["size_tier"] == "significant"  # $1100 >= 1000

    def test_detail_zero_code(self, client: TestClient):
        body = client.get(f"/api/cost-coding/9999.ZERO?{THRESHOLD_QS}").json()
        assert body["cost_category"] == "zero"
        assert body["size_tier"] == "zero"
        assert body["total_direct_cost"] == 0.0

    def test_unknown_code_returns_404(self, client: TestClient):
        resp = client.get(f"/api/cost-coding/not-a-code?{THRESHOLD_QS}")
        assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# /insights                                                                   #
# --------------------------------------------------------------------------- #


class TestInsights:
    def test_category_breakdown(self, client: TestClient):
        body = client.get(
            f"/api/cost-coding/insights?{THRESHOLD_QS}"
        ).json()
        cb = body["category_breakdown"]
        assert cb["labor"] == 1              # 1101.100
        assert cb["permanent_material"] == 1  # 2300.001
        assert cb["construction_material"] == 0
        assert cb["equipment"] == 1          # 2700.150
        assert cb["subcontract"] == 0
        assert cb["mixed"] == 1              # 9500.900
        assert cb["zero"] == 1               # 9999.ZERO

    def test_size_tier_breakdown(self, client: TestClient):
        body = client.get(
            f"/api/cost-coding/insights?{THRESHOLD_QS}"
        ).json()
        st = body["size_tier_breakdown"]
        # major: 2300.001 ($8700), 2700.150 ($6000) = 2
        assert st["major"] == 2
        # significant: 1101.100 ($3000), 9500.900 ($1100) = 2
        assert st["significant"] == 2
        assert st["minor"] == 0
        # zero: 9999.ZERO = 1
        assert st["zero"] == 1

    def test_usage_tier_breakdown(self, client: TestClient):
        body = client.get(
            f"/api/cost-coding/insights?{THRESHOLD_QS}"
        ).json()
        ut = body["usage_tier_breakdown"]
        assert ut["heavy"] == 1      # 1101.100 (3 estimates)
        assert ut["regular"] == 3    # 2300.001, 2700.150, 9999.ZERO (2 each)
        assert ut["light"] == 0
        assert ut["singleton"] == 1  # 9500.900

    def test_category_mix_share(self, client: TestClient):
        body = client.get(
            f"/api/cost-coding/insights?{THRESHOLD_QS}"
        ).json()
        mix = {row["category"]: row for row in body["category_mix"]}
        # Total of the 5 buckets we sum for mix:
        # labor 3700 + perm 8300 + const 100 + equip 6250 + sub 250 = 18600
        total_bucket = 3700 + 8300 + 100 + 6250 + 250
        assert mix["labor"]["total_direct_cost"] == 3700.0
        assert mix["labor"]["share_of_total"] == round(3700 / total_bucket, 4)
        assert mix["permanent_material"]["share_of_total"] == round(
            8300 / total_bucket, 4
        )
        # code_count in the mix mirrors the *dominant* category counts
        assert mix["labor"]["code_count"] == 1

    def test_top_by_cost(self, client: TestClient):
        body = client.get(
            f"/api/cost-coding/insights?{THRESHOLD_QS}"
        ).json()
        codes = [row["code"] for row in body["top_by_cost"]]
        # Ordering: 2300.001 ($8700), 2700.150 ($6000), 1101.100 ($3000),
        # 9500.900 ($1100), 9999.ZERO ($0)
        assert codes == ["2300.001", "2700.150", "1101.100", "9500.900", "9999.ZERO"]

    def test_top_by_usage(self, client: TestClient):
        body = client.get(
            f"/api/cost-coding/insights?{THRESHOLD_QS}"
        ).json()
        # Top is 1101.100 (3 estimates)
        assert body["top_by_usage"][0]["code"] == "1101.100"
        assert body["top_by_usage"][0]["estimate_count"] == 3

    def test_top_by_hours(self, client: TestClient):
        body = client.get(
            f"/api/cost-coding/insights?{THRESHOLD_QS}"
        ).json()
        # 1101.100 has 120 hours total (40+50+30), the highest.
        assert body["top_by_hours"][0]["code"] == "1101.100"
        assert body["top_by_hours"][0]["total_man_hours"] == 120.0

    def test_top_major_codes(self, client: TestClient):
        body = client.get(
            f"/api/cost-coding/insights?{THRESHOLD_QS}"
        ).json()
        majors = {row["major_code"]: row for row in body["top_major_codes"]}
        # Major codes: 1101, 2300, 2700, 9500, 9999
        assert set(majors.keys()) == {"1101", "2300", "2700", "9500", "9999"}
        # Each major maps to one code in this seed — code_count=1 everywhere.
        for row in majors.values():
            assert row["code_count"] == 1
        assert majors["2300"]["total_direct_cost"] == 8700.0

    def test_uncosted_codes(self, client: TestClient):
        body = client.get(
            f"/api/cost-coding/insights?{THRESHOLD_QS}"
        ).json()
        uncosted = [row["code"] for row in body["uncosted_codes"]]
        assert uncosted == ["9999.ZERO"]

    def test_top_n_caps(self, client: TestClient):
        body = client.get(
            f"/api/cost-coding/insights?top_n=2&{THRESHOLD_QS}"
        ).json()
        assert len(body["top_by_cost"]) == 2
        assert len(body["top_by_usage"]) == 2
        assert len(body["top_by_hours"]) == 2
        assert len(body["top_major_codes"]) == 2
