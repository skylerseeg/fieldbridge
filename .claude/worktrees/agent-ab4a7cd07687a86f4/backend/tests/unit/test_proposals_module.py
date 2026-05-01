"""Tests for app.modules.proposals.

Strategy mirrors the other mart-backed modules:
  1. Fresh SQLite DB per test via fixtures.
  2. Register every mart Table against Base.metadata, create_all().
  3. Seed canonical proposals covering every bid_type_category
     (pressurized/structures/concrete/earthwork/other) and every
     geography_tier (in_state/out_of_state/unknown).
  4. Seed a handful of line items in ``mart_proposal_line_items``
     (tenant-wide pool, not linked to proposals yet).
  5. Drive the API through TestClient with dependency overrides.

Canonical seed — seven proposals:

  Job              Owner        bid_type                       county         category     geo
  Water Main Job   Alpine City  Pressurized Water Main         Utah, UT       PRESSURIZED  IN_STATE
  Irrigation Main  Alpine City  Pressurized Irrigation         Utah, UT       PRESSURIZED  IN_STATE
  Vault Job        County       Precast Vault Install          Clark, NV      STRUCTURES   OUT_OF_STATE
  Slab Job         City         Concrete Slab Replacement      Beaver, UT     CONCRETE     IN_STATE
  Grading Project  DOT          Mass Earthwork Grading         (null)         EARTHWORK    UNKNOWN
  Coating Job      Industrial   Specialty Coating              Washoe, NV     OTHER        OUT_OF_STATE
  Unparseable      NoState Co   Misc Work                      "Rural Area"   OTHER        UNKNOWN

Primary state default is ``UT``.
"""
from __future__ import annotations

import hashlib
import json
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
from app.modules.proposals.router import (
    _default_engine,
    get_engine,
    get_tenant_id,
    router as proposals_router,
)
from app.modules.proposals.schema import (
    BidTypeCategory,
    GeographyTier,
)
from app.modules.proposals.service import (
    _bid_type_category,
    _geography_tier,
    _parse_state,
    _proposal_id,
)


# --------------------------------------------------------------------------- #
# Canonical seed                                                              #
# --------------------------------------------------------------------------- #


PROPOSAL_SEEDS: list[dict] = [
    # PRESSURIZED / IN_STATE
    {
        "job": "Water Main Job",
        "owner": "Alpine City",
        "bid_type": "Pressurized Water Main",
        "county": "Utah, UT",
    },
    # PRESSURIZED / IN_STATE (repeat owner + county to exercise top_owners)
    {
        "job": "Irrigation Main",
        "owner": "Alpine City",
        "bid_type": "Pressurized Irrigation",
        "county": "Utah, UT",
    },
    # STRUCTURES / OUT_OF_STATE
    {
        "job": "Vault Job",
        "owner": "Clark County",
        "bid_type": "Precast Vault Install",
        "county": "Clark, NV",
    },
    # CONCRETE / IN_STATE
    {
        "job": "Slab Job",
        "owner": "Beaver City",
        "bid_type": "Concrete Slab Replacement",
        "county": "Beaver, UT",
    },
    # EARTHWORK / UNKNOWN (null county)
    {
        "job": "Grading Project",
        "owner": "State DOT",
        "bid_type": "Mass Earthwork Grading",
        "county": None,
    },
    # OTHER / OUT_OF_STATE
    {
        "job": "Coating Job",
        "owner": "Industrial Co",
        "bid_type": "Specialty Coating",
        "county": "Washoe, NV",
    },
    # OTHER / UNKNOWN (county without a parseable state suffix)
    {
        "job": "Unparseable Job",
        "owner": "NoState Co",
        "bid_type": "Misc Work",
        "county": "Rural Area",
    },
]


LINE_ITEM_SEEDS: list[dict] = [
    {
        "competitor": "Alpha Builders",
        "design_fee": 10,
        "cm_fee": 20,
        "cm_monthly_fee": 30,
        "contractor_ohp_fee": 40,
        "contractor_bonds_ins": 50,
        "contractor_co_markup": 60,
        "city_budget": 100,
        "contractor_days": 30,
        "contractor_projects": 5,
        "pm_projects": 3,
    },
    {
        "competitor": "Beta Construction",
        "design_fee": 15,
        "cm_fee": 25,
        "contractor_ohp_fee": 45,
        "contractor_co_markup": 55,
        "city_budget": 200,
    },
    {
        # Repeat competitor with no fees — exercises competitor_frequency.
        "competitor": "Alpha Builders",
    },
    {
        # No competitor — exercises `line_items_with_competitor` count.
        "design_fee": 5,
        "city_budget": 150,
    },
]


PROPOSAL_INSERT_SQL = text(
    """
    INSERT INTO mart_proposals (tenant_id, job, owner, bid_type, county)
    VALUES (:tenant_id, :job, :owner, :bid_type, :county)
    """
)


_LINE_ITEM_COLS: list[str] = [
    "competitor", "design_fee", "cm_fee", "cm_monthly_fee",
    "contractor_ohp_fee", "contractor_bonds_ins", "contractor_co_markup",
    "city_budget", "contractor_start", "contractor_days",
    "contractor_projects", "pm_projects", "contractor_pm",
    "contractor_super", "reference_1", "reference_2", "reference_3",
]


def _row_hash_for(row: dict) -> str:
    payload = json.dumps(row, sort_keys=True, default=str)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def _line_item_insert_sql() -> text:
    cols = ["tenant_id", "_row_hash"] + _LINE_ITEM_COLS
    col_sql = ", ".join(cols)
    val_sql = ", ".join(f":{c}" for c in cols)
    return text(
        f"INSERT INTO mart_proposal_line_items ({col_sql}) VALUES ({val_sql})"
    )


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def seeded_engine(tmp_path) -> Engine:
    url = f"sqlite:///{tmp_path / 'proposals_test.db'}"
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
        for row in PROPOSAL_SEEDS:
            conn.execute(PROPOSAL_INSERT_SQL, {"tenant_id": tenant_id, **row})
        for i, row in enumerate(LINE_ITEM_SEEDS):
            payload = {c: row.get(c) for c in _LINE_ITEM_COLS}
            payload["tenant_id"] = tenant_id
            # Use (index + full payload) for stable unique _row_hash.
            payload["_row_hash"] = _row_hash_for({"_i": i, **payload})
            conn.execute(_line_item_insert_sql(), payload)

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
    app.include_router(proposals_router, prefix="/api/proposals")

    app.dependency_overrides[get_engine] = lambda: seeded_engine
    app.dependency_overrides[get_tenant_id] = lambda: seeded_tenant_id

    _default_engine.cache_clear()

    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# Pure helpers                                                                #
# --------------------------------------------------------------------------- #


class TestProposalId:
    def test_stable(self):
        assert (
            _proposal_id("Water Main Job", "Alpine City", "Pressurized Water Main")
            == _proposal_id("Water Main Job", "Alpine City", "Pressurized Water Main")
        )

    def test_differs_by_owner(self):
        assert (
            _proposal_id("J", "A", "T") != _proposal_id("J", "B", "T")
        )

    def test_12_hex(self):
        out = _proposal_id("J", "A", "T")
        assert len(out) == 12
        int(out, 16)

    def test_handles_none(self):
        out = _proposal_id(None, None, None)
        assert len(out) == 12


class TestParseState:
    def test_basic(self):
        assert _parse_state("Utah, UT") == "UT"

    def test_lowercase_is_uppercased(self):
        assert _parse_state("Clark, nv") == "NV"

    def test_no_comma(self):
        assert _parse_state("Rural Area") is None

    def test_non_two_char(self):
        assert _parse_state("Something, Utah") is None  # "UTAH" → 4 chars

    def test_two_char_county_no_comma(self):
        # Bare "UT" has no comma, so rpartition returns ('', '', 'UT')
        # and the raw token is 2 chars → state=UT.
        assert _parse_state("UT") == "UT"

    def test_none(self):
        assert _parse_state(None) is None

    def test_empty(self):
        assert _parse_state("") is None


class TestBidTypeCategoryHelper:
    def test_pressurized_word(self):
        assert _bid_type_category("Pressurized Water Main") is BidTypeCategory.PRESSURIZED

    def test_water_word(self):
        assert _bid_type_category("Water Transmission") is BidTypeCategory.PRESSURIZED

    def test_irrigation_word(self):
        assert _bid_type_category("Irrigation Upgrade") is BidTypeCategory.PRESSURIZED

    def test_structures_word(self):
        assert _bid_type_category("Concrete Structure Rebuild") is BidTypeCategory.STRUCTURES

    def test_vault_word(self):
        assert _bid_type_category("Precast Vault Install") is BidTypeCategory.STRUCTURES

    def test_concrete_fallback(self):
        assert _bid_type_category("Concrete Slab Replacement") is BidTypeCategory.CONCRETE

    def test_earthwork(self):
        assert _bid_type_category("Mass Earthwork Grading") is BidTypeCategory.EARTHWORK

    def test_excav(self):
        assert _bid_type_category("Excavation and Backfill") is BidTypeCategory.EARTHWORK

    def test_other_fallback(self):
        assert _bid_type_category("Specialty Coating") is BidTypeCategory.OTHER

    def test_none(self):
        assert _bid_type_category(None) is BidTypeCategory.OTHER

    def test_empty(self):
        assert _bid_type_category("") is BidTypeCategory.OTHER


class TestGeographyTierHelper:
    def test_in_state(self):
        assert _geography_tier("UT", primary_state="UT") is GeographyTier.IN_STATE

    def test_in_state_case_insensitive(self):
        assert _geography_tier("ut", primary_state="UT") is GeographyTier.IN_STATE

    def test_out_of_state(self):
        assert _geography_tier("NV", primary_state="UT") is GeographyTier.OUT_OF_STATE

    def test_unknown_for_none(self):
        assert _geography_tier(None, primary_state="UT") is GeographyTier.UNKNOWN

    def test_alternate_primary(self):
        assert _geography_tier("NV", primary_state="NV") is GeographyTier.IN_STATE


# --------------------------------------------------------------------------- #
# /summary                                                                    #
# --------------------------------------------------------------------------- #


class TestSummary:
    def test_totals(self, client: TestClient):
        body = client.get("/api/proposals/summary").json()
        assert body["total_proposals"] == 7

    def test_distinct_counts(self, client: TestClient):
        body = client.get("/api/proposals/summary").json()
        # Owners: Alpine City, Clark County, Beaver City, State DOT,
        # Industrial Co, NoState Co = 6
        assert body["distinct_owners"] == 6
        # bid_types are all different strings → 7 distinct
        assert body["distinct_bid_types"] == 7
        # Counties: Utah UT (2x), Clark NV, Beaver UT, Washoe NV, Rural Area = 5
        assert body["distinct_counties"] == 5
        # State codes parsed: UT, NV = 2 (Rural Area + null both unparseable)
        assert body["distinct_states"] == 2

    def test_geography_counts(self, client: TestClient):
        body = client.get("/api/proposals/summary").json()
        # IN_STATE: Water Main, Irrigation Main, Slab Job = 3
        assert body["in_state_proposals"] == 3
        # OUT_OF_STATE: Vault Job, Coating Job = 2
        assert body["out_of_state_proposals"] == 2
        # UNKNOWN: Grading Project (null), Unparseable Job = 2
        assert body["unknown_geography_proposals"] == 2

    def test_primary_state_override(self, client: TestClient):
        # If we switch to NV as primary, counts flip.
        body = client.get("/api/proposals/summary?primary_state=NV").json()
        assert body["in_state_proposals"] == 2
        assert body["out_of_state_proposals"] == 3

    def test_line_item_counts(self, client: TestClient):
        body = client.get("/api/proposals/summary").json()
        assert body["total_line_items"] == 4
        # 3 line items have competitor (Alpha x2, Beta), one has none.
        assert body["line_items_with_competitor"] == 3
        assert body["distinct_competitors"] == 2  # Alpha + Beta

    def test_city_budget_stats(self, client: TestClient):
        body = client.get("/api/proposals/summary").json()
        # city_budget values: 100, 200, 150 → total 450, avg 150
        assert body["total_city_budget"] == 450
        assert body["avg_city_budget"] == pytest.approx(150.0)


# --------------------------------------------------------------------------- #
# /list                                                                       #
# --------------------------------------------------------------------------- #


class TestList:
    def test_default_pagination(self, client: TestClient):
        body = client.get("/api/proposals/list").json()
        assert body["total"] == 7
        assert body["page"] == 1
        assert body["page_size"] == 25
        assert len(body["items"]) == 7

    def test_sort_by_job_asc_default(self, client: TestClient):
        body = client.get("/api/proposals/list").json()
        jobs = [r["job"] for r in body["items"]]
        assert jobs == sorted(jobs, key=str.lower)

    def test_sort_by_owner_desc(self, client: TestClient):
        body = client.get(
            "/api/proposals/list?sort_by=owner&sort_dir=desc"
        ).json()
        owners = [r["owner"] for r in body["items"]]
        assert owners == sorted(owners, key=str.lower, reverse=True)

    def test_sort_by_county_nulls_last(self, client: TestClient):
        body = client.get(
            "/api/proposals/list?sort_by=county&sort_dir=asc"
        ).json()
        # Grading Project (null county) should land at the end.
        assert body["items"][-1]["job"] == "Grading Project"

    def test_pagination(self, client: TestClient):
        body = client.get("/api/proposals/list?page=1&page_size=3").json()
        assert len(body["items"]) == 3
        body2 = client.get("/api/proposals/list?page=3&page_size=3").json()
        assert len(body2["items"]) == 1  # 7 total

    def test_filter_bid_type_category_pressurized(self, client: TestClient):
        body = client.get(
            "/api/proposals/list?bid_type_category=pressurized"
        ).json()
        assert body["total"] == 2
        assert {r["job"] for r in body["items"]} == {
            "Water Main Job", "Irrigation Main",
        }

    def test_filter_bid_type_category_structures(self, client: TestClient):
        body = client.get(
            "/api/proposals/list?bid_type_category=structures"
        ).json()
        assert body["total"] == 1
        assert body["items"][0]["job"] == "Vault Job"

    def test_filter_bid_type_category_concrete(self, client: TestClient):
        body = client.get(
            "/api/proposals/list?bid_type_category=concrete"
        ).json()
        assert body["total"] == 1
        assert body["items"][0]["job"] == "Slab Job"

    def test_filter_bid_type_category_earthwork(self, client: TestClient):
        body = client.get(
            "/api/proposals/list?bid_type_category=earthwork"
        ).json()
        assert body["total"] == 1
        assert body["items"][0]["job"] == "Grading Project"

    def test_filter_bid_type_category_other(self, client: TestClient):
        body = client.get(
            "/api/proposals/list?bid_type_category=other"
        ).json()
        # Coating Job + Unparseable Job.
        assert body["total"] == 2

    def test_filter_geography_in_state(self, client: TestClient):
        body = client.get(
            "/api/proposals/list?geography_tier=in_state"
        ).json()
        assert body["total"] == 3

    def test_filter_geography_out_of_state(self, client: TestClient):
        body = client.get(
            "/api/proposals/list?geography_tier=out_of_state"
        ).json()
        assert body["total"] == 2

    def test_filter_geography_unknown(self, client: TestClient):
        body = client.get(
            "/api/proposals/list?geography_tier=unknown"
        ).json()
        assert body["total"] == 2

    def test_filter_owner(self, client: TestClient):
        body = client.get(
            "/api/proposals/list?owner=Alpine%20City"
        ).json()
        assert body["total"] == 2

    def test_filter_bid_type_exact(self, client: TestClient):
        body = client.get(
            "/api/proposals/list?bid_type=Concrete%20Slab%20Replacement"
        ).json()
        assert body["total"] == 1

    def test_filter_county_exact(self, client: TestClient):
        body = client.get(
            "/api/proposals/list?county=Utah%2C%20UT"
        ).json()
        assert body["total"] == 2

    def test_filter_state_code(self, client: TestClient):
        body = client.get("/api/proposals/list?state_code=NV").json()
        # Vault Job + Coating Job.
        assert body["total"] == 2

    def test_filter_state_code_case_insensitive(self, client: TestClient):
        body = client.get("/api/proposals/list?state_code=nv").json()
        assert body["total"] == 2

    def test_search_substring_on_job(self, client: TestClient):
        body = client.get("/api/proposals/list?search=vault").json()
        assert body["total"] == 1
        assert body["items"][0]["job"] == "Vault Job"

    def test_search_substring_on_owner(self, client: TestClient):
        body = client.get("/api/proposals/list?search=alpine").json()
        assert body["total"] == 2

    def test_search_substring_on_bid_type(self, client: TestClient):
        body = client.get("/api/proposals/list?search=coating").json()
        assert body["total"] == 1

    def test_primary_state_override_changes_tier(self, client: TestClient):
        # Under primary_state=NV, NV rows become IN_STATE.
        body = client.get(
            "/api/proposals/list?geography_tier=in_state&primary_state=NV"
        ).json()
        jobs = {r["job"] for r in body["items"]}
        assert jobs == {"Vault Job", "Coating Job"}

    def test_list_row_fields_populated(self, client: TestClient):
        body = client.get(
            "/api/proposals/list?sort_by=job&bid_type_category=pressurized"
        ).json()
        row = body["items"][0]
        assert "id" in row and len(row["id"]) == 12
        assert row["bid_type_category"] == "pressurized"
        assert row["geography_tier"] == "in_state"
        assert row["state_code"] == "UT"


# --------------------------------------------------------------------------- #
# /{proposal_id}                                                              #
# --------------------------------------------------------------------------- #


class TestDetail:
    def _make_id(self, job: str, owner: str, bid_type: str) -> str:
        return _proposal_id(job, owner, bid_type)

    def test_404_for_missing(self, client: TestClient):
        resp = client.get("/api/proposals/deadbeefdead")
        assert resp.status_code == 404

    def test_fetches_water_main(self, client: TestClient):
        pid = self._make_id(
            "Water Main Job", "Alpine City", "Pressurized Water Main"
        )
        resp = client.get(f"/api/proposals/{pid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == pid
        assert body["job"] == "Water Main Job"
        assert body["owner"] == "Alpine City"
        assert body["bid_type"] == "Pressurized Water Main"
        assert body["county"] == "Utah, UT"
        assert body["state_code"] == "UT"
        assert body["bid_type_category"] == "pressurized"
        assert body["geography_tier"] == "in_state"

    def test_fetches_null_county(self, client: TestClient):
        pid = self._make_id(
            "Grading Project", "State DOT", "Mass Earthwork Grading"
        )
        body = client.get(f"/api/proposals/{pid}").json()
        assert body["county"] is None
        assert body["state_code"] is None
        assert body["geography_tier"] == "unknown"

    def test_primary_state_override(self, client: TestClient):
        pid = self._make_id(
            "Vault Job", "Clark County", "Precast Vault Install"
        )
        body = client.get(
            f"/api/proposals/{pid}?primary_state=NV"
        ).json()
        assert body["geography_tier"] == "in_state"


# --------------------------------------------------------------------------- #
# /insights                                                                   #
# --------------------------------------------------------------------------- #


class TestInsights:
    def test_bid_type_category_breakdown(self, client: TestClient):
        body = client.get("/api/proposals/insights").json()
        b = body["bid_type_category_breakdown"]
        assert b["pressurized"] == 2
        assert b["structures"] == 1
        assert b["concrete"] == 1
        assert b["earthwork"] == 1
        assert b["other"] == 2

    def test_geography_breakdown(self, client: TestClient):
        body = client.get("/api/proposals/insights").json()
        g = body["geography_tier_breakdown"]
        assert g["in_state"] == 3
        assert g["out_of_state"] == 2
        assert g["unknown"] == 2

    def test_top_owners(self, client: TestClient):
        body = client.get("/api/proposals/insights").json()
        rows = {r["segment"]: r["count"] for r in body["top_owners"]}
        # Alpine City is the only repeat owner (2).
        assert rows["Alpine City"] == 2
        # Others are 1 each.
        assert rows["Clark County"] == 1

    def test_top_counties(self, client: TestClient):
        body = client.get("/api/proposals/insights").json()
        rows = {r["segment"]: r["count"] for r in body["top_counties"]}
        # Utah, UT appears twice.
        assert rows["Utah, UT"] == 2

    def test_top_states(self, client: TestClient):
        body = client.get("/api/proposals/insights").json()
        rows = {r["segment"]: r["count"] for r in body["top_states"]}
        # UT: Water, Irrigation, Slab = 3; NV: Vault + Coating = 2.
        assert rows["UT"] == 3
        assert rows["NV"] == 2

    def test_competitor_frequency(self, client: TestClient):
        body = client.get("/api/proposals/insights").json()
        rows = {
            r["competitor"]: r["line_item_count"]
            for r in body["competitor_frequency"]
        }
        assert rows["Alpha Builders"] == 2
        assert rows["Beta Construction"] == 1

    def test_fee_statistics(self, client: TestClient):
        body = client.get("/api/proposals/insights").json()
        by_fee = {r["fee"]: r for r in body["fee_statistics"]}

        # design_fee: 10, 15, 5 → count=3, min=5, max=15, avg=10.0
        df = by_fee["design_fee"]
        assert df["count"] == 3
        assert df["min_value"] == 5
        assert df["max_value"] == 15
        assert df["avg_value"] == pytest.approx(10.0)

        # cm_fee: 20, 25 → count=2, avg=22.5
        cm = by_fee["cm_fee"]
        assert cm["count"] == 2
        assert cm["avg_value"] == pytest.approx(22.5)

        # city_budget: 100, 200, 150 → count=3, min=100, max=200, avg=150.0
        cb = by_fee["city_budget"]
        assert cb["count"] == 3
        assert cb["min_value"] == 100
        assert cb["max_value"] == 200
        assert cb["avg_value"] == pytest.approx(150.0)

        # cm_monthly_fee: only L1 (30) → count=1
        cmm = by_fee["cm_monthly_fee"]
        assert cmm["count"] == 1
        assert cmm["avg_value"] == pytest.approx(30.0)

    def test_top_n_limit(self, client: TestClient):
        body = client.get("/api/proposals/insights?top_n=1").json()
        assert len(body["top_owners"]) == 1
        assert len(body["top_bid_types"]) == 1
        assert len(body["top_counties"]) == 1
        # Alpine City has highest count (2), appears first.
        assert body["top_owners"][0]["segment"] == "Alpine City"

    def test_primary_state_override(self, client: TestClient):
        body = client.get(
            "/api/proposals/insights?primary_state=NV"
        ).json()
        g = body["geography_tier_breakdown"]
        assert g["in_state"] == 2  # NV proposals now in_state
        assert g["out_of_state"] == 3


# --------------------------------------------------------------------------- #
# Cross-cutting                                                               #
# --------------------------------------------------------------------------- #


class TestEmptyTenant:
    def test_summary_empty(self, seeded_engine: Engine):
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
        app.include_router(proposals_router, prefix="/api/proposals")
        app.dependency_overrides[get_engine] = lambda: seeded_engine
        app.dependency_overrides[get_tenant_id] = lambda: empty_id
        _default_engine.cache_clear()

        with TestClient(app) as c:
            body = c.get("/api/proposals/summary").json()

        assert body["total_proposals"] == 0
        assert body["total_line_items"] == 0
        assert body["total_city_budget"] == 0
        assert body["avg_city_budget"] == 0.0

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
        app.include_router(proposals_router, prefix="/api/proposals")
        app.dependency_overrides[get_engine] = lambda: seeded_engine
        app.dependency_overrides[get_tenant_id] = lambda: empty_id
        _default_engine.cache_clear()

        with TestClient(app) as c:
            body = c.get("/api/proposals/insights").json()

        assert body["bid_type_category_breakdown"] == {
            "pressurized": 0, "structures": 0, "concrete": 0,
            "earthwork": 0, "other": 0,
        }
        assert body["top_owners"] == []
        assert body["competitor_frequency"] == []
        # Fee statistics rows are emitted per-fee with count=0.
        for fee_row in body["fee_statistics"]:
            assert fee_row["count"] == 0
            assert fee_row["avg_value"] is None
