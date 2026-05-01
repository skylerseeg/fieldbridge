"""Tests for app.modules.vendors.

Strategy mirrors the other mart-backed modules:
  1. Fresh SQLite DB per test via fixtures.
  2. Register every mart Table against Base.metadata, create_all().
  3. Seed a small, canonical directory that spans every firm type,
     contact-status tier, and coding tier so each endpoint has
     something deterministic to count.
  4. Drive the API through TestClient with dependency overrides.

Canonical seed (7 rows):

  #  Name                Firm        Contact  Email    Phone    Codes
  1  Acme Concrete Co    Contractor  y        y        y        0330, 0350, 0360   (division 03 x3)
  2  Rocky Mtn Supply    Supplier    y        n        n        2600               (division 26)
  3  BlueStone Masonry   Contractor  n        y        n        0422, 0471         (division 04 x2)
  4  Precision Surveyors Service     n        n        n        (none)
  5  VanCon Self         Internal    y        y        y        0130               (division 01)
  6  (null)              (null)      n        n        n        (none)             EMPTY / UNCODED / UNKNOWN
  7  '  Acme Concrete Co  ' (dupe whitespace) — collision-test row, name-only

That gives us: 2 contractors, 1 supplier, 1 service, 1 internal, 2
unknown; 2 COMPLETE contact rows, 1 PARTIAL (BlueStone email only),
1 MINIMAL (Precision — name only, no channel), 2 EMPTY (null-name +
the whitespace-dupe's normalization lands on the same id as Acme —
wait, the dupe is explicitly EXCLUDED and we use 6 rows; see
``SEEDS`` below).
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
from app.modules.vendors import insights as vendors_insights
from app.modules.vendors.router import (
    _default_engine,
    get_engine,
    get_tenant_id,
    router as vendors_router,
)
from app.modules.vendors.service import (
    _coding_status,
    _contact_status,
    _division,
    _firm_type,
    _norm_name,
)


# --------------------------------------------------------------------------- #
# Canonical seed                                                              #
# --------------------------------------------------------------------------- #


SEEDS: list[dict] = [
    # 1. Full contractor, 3 codes all in division 03 (Concrete)
    {
        "name": "Acme Concrete Co",
        "firm_type": "Contractor",
        "contact": "Alice A.",
        "title": "PM",
        "email": "alice@acme.test",
        "phone": "555-0101",
        "code_1": "0330-Cast-in-place Concrete",
        "code_2": "0350-Precast",
        "code_3": "0360-Grouting",
        "code_4": None,
        "code_5": None,
    },
    # 2. Supplier with one code in division 26 (Electrical), no contact channel
    {
        "name": "Rocky Mtn Supply",
        "firm_type": "Supplier",
        "contact": "Rick R.",
        "title": None,
        "email": None,
        "phone": None,
        "code_1": "2600-Electrical",
        "code_2": None,
        "code_3": None,
        "code_4": None,
        "code_5": None,
    },
    # 3. Contractor with 2 codes in division 04 (Masonry), partial contact
    {
        "name": "BlueStone Masonry",
        "firm_type": "contractor",   # lowercase on purpose — mapper trims/lowers
        "contact": None,
        "title": None,
        "email": "ops@bluestone.test",
        "phone": None,
        "code_1": "0422-Concrete Unit Masonry",
        "code_2": "0471-Manufactured Stone",
        "code_3": None,
        "code_4": None,
        "code_5": None,
    },
    # 4. Service firm, zero codes, zero contact channels — MINIMAL contact, UNCODED
    {
        "name": "Precision Surveyors",
        "firm_type": "Service",
        "contact": None,
        "title": None,
        "email": None,
        "phone": None,
        "code_1": None,
        "code_2": None,
        "code_3": None,
        "code_4": None,
        "code_5": None,
    },
    # 5. Internal row (VanCon itself) — COMPLETE contact, 1 code in division 01
    {
        "name": "VanCon Self",
        "firm_type": "Internal",
        "contact": "Valerie V.",
        "title": "Admin",
        "email": "admin@vancon.test",
        "phone": "555-0001",
        "code_1": "0130-General Requirements",
        "code_2": None,
        "code_3": None,
        "code_4": None,
        "code_5": None,
    },
    # 6. Null-name stub — EMPTY contact, UNKNOWN firm_type, UNCODED
    {
        "name": None,
        "firm_type": None,
        "contact": None,
        "title": None,
        "email": None,
        "phone": None,
        "code_1": None,
        "code_2": None,
        "code_3": None,
        "code_4": None,
        "code_5": None,
    },
]


INSERT_SQL = text(
    """
    INSERT INTO mart_vendors
        (tenant_id, _row_hash, name, firm_type, contact, title, email, phone,
         code_1, code_2, code_3, code_4, code_5)
    VALUES
        (:tenant_id, :_row_hash, :name, :firm_type, :contact, :title, :email,
         :phone, :code_1, :code_2, :code_3, :code_4, :code_5)
    """
)

def _row_hash_for(row: dict) -> str:
    """Stable per-seed hash so seeds remain deterministic across runs."""
    payload = json.dumps(row, sort_keys=True, default=str)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def seeded_engine(tmp_path) -> Engine:
    url = f"sqlite:///{tmp_path / 'vendors_test.db'}"
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
            conn.execute(
                INSERT_SQL,
                {"tenant_id": tenant_id, "_row_hash": _row_hash_for(row), **row},
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
    app.include_router(vendors_router, prefix="/api/vendors")

    app.dependency_overrides[get_engine] = lambda: seeded_engine
    app.dependency_overrides[get_tenant_id] = lambda: seeded_tenant_id

    _default_engine.cache_clear()

    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# Pure helpers                                                                #
# --------------------------------------------------------------------------- #


class TestNormName:
    def test_strips_and_collapses_whitespace(self):
        assert _norm_name("  Acme   Concrete\tCo  ") == "Acme Concrete Co"

    def test_none_returns_none(self):
        assert _norm_name(None) is None

    def test_empty_string_returns_none(self):
        assert _norm_name("   ") is None


class TestFirmType:
    def test_canonical_values(self):
        assert _firm_type("Supplier").value == "supplier"
        assert _firm_type("contractor").value == "contractor"
        assert _firm_type(" SERVICE ").value == "service"
        assert _firm_type("Internal").value == "internal"

    def test_unknown_for_missing_or_weird(self):
        assert _firm_type(None).value == "unknown"
        assert _firm_type("Mystery").value == "unknown"


class TestDivision:
    def test_prefix_extraction(self):
        assert _division("0330-Cast-in-place Concrete") == "03"
        assert _division("2600-Electrical") == "26"

    def test_non_digit_prefix_is_none(self):
        assert _division("ABC") is None

    def test_empty_and_none(self):
        assert _division(None) is None
        assert _division("") is None


class TestContactStatus:
    def test_complete_needs_all_three_channels(self):
        status = _contact_status(
            {
                "name": "X",
                "contact": "a",
                "email": "b",
                "phone": "c",
            }
        )
        assert status.value == "complete"

    def test_partial_any_one_channel(self):
        status = _contact_status(
            {"name": "X", "contact": None, "email": "b", "phone": None}
        )
        assert status.value == "partial"

    def test_minimal_name_only(self):
        status = _contact_status(
            {"name": "X", "contact": None, "email": None, "phone": None}
        )
        assert status.value == "minimal"

    def test_empty_no_name(self):
        status = _contact_status(
            {"name": None, "contact": "a", "email": "b", "phone": "c"}
        )
        assert status.value == "empty"


class TestCodingStatus:
    def test_coded_when_any_code(self):
        assert _coding_status(["0330"]).value == "coded"

    def test_uncoded_when_empty(self):
        assert _coding_status([]).value == "uncoded"


# --------------------------------------------------------------------------- #
# /summary                                                                    #
# --------------------------------------------------------------------------- #


class TestSummary:
    def test_totals(self, client: TestClient):
        resp = client.get("/api/vendors/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_vendors"] == 6

    def test_contact_health_counts(self, client: TestClient):
        body = client.get("/api/vendors/summary").json()
        # Names: rows 1-5 have names, row 6 is null → 5
        assert body["with_name"] == 5
        # Contact col populated on rows 1, 2, 5 → 3
        assert body["with_contact"] == 3
        # Email col populated on rows 1, 3, 5 → 3
        assert body["with_email"] == 3
        # Phone col populated on rows 1, 5 → 2
        assert body["with_phone"] == 2
        # Complete = rows 1 and 5 (all four of name/contact/email/phone)
        assert body["complete_contact"] == 2

    def test_firm_type_mix(self, client: TestClient):
        body = client.get("/api/vendors/summary").json()
        assert body["suppliers"] == 1
        assert body["contractors"] == 2
        assert body["services"] == 1
        assert body["internal"] == 1
        assert body["unknown_firm_type"] == 1

    def test_coding_counts(self, client: TestClient):
        body = client.get("/api/vendors/summary").json()
        # Coded: rows 1, 2, 3, 5 → 4
        assert body["coded_vendors"] == 4
        # Uncoded: rows 4 (Precision) and 6 (null) → 2
        assert body["uncoded_vendors"] == 2
        # Distinct codes across all vendors: 0330, 0350, 0360, 2600,
        # 0422, 0471, 0130 → 7
        assert body["distinct_codes"] == 7
        # Distinct divisions: 03, 26, 04, 01 → 4
        assert body["distinct_divisions"] == 4


# --------------------------------------------------------------------------- #
# /list                                                                       #
# --------------------------------------------------------------------------- #


class TestList:
    def test_default_pagination(self, client: TestClient):
        resp = client.get("/api/vendors/list")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 6
        assert body["page"] == 1
        assert body["page_size"] == 25
        assert len(body["items"]) == 6

    def test_null_names_sort_last_ascending(self, client: TestClient):
        body = client.get(
            "/api/vendors/list?sort_by=name&sort_dir=asc"
        ).json()
        names = [r["name"] for r in body["items"]]
        # Last item must be the null-name row
        assert names[-1] is None
        # Everything before must be non-null and sorted
        non_null = [n for n in names if n is not None]
        assert non_null == sorted(non_null, key=str.lower)

    def test_null_names_sort_last_descending(self, client: TestClient):
        body = client.get(
            "/api/vendors/list?sort_by=name&sort_dir=desc"
        ).json()
        names = [r["name"] for r in body["items"]]
        assert names[-1] is None
        non_null = [n for n in names if n is not None]
        assert non_null == sorted(non_null, key=str.lower, reverse=True)

    def test_sort_by_code_count_desc(self, client: TestClient):
        body = client.get(
            "/api/vendors/list?sort_by=code_count&sort_dir=desc"
        ).json()
        code_counts = [r["code_count"] for r in body["items"]]
        # Acme has 3, then BlueStone 2, then Rocky/VanCon at 1, then 0s.
        assert code_counts[0] == 3
        assert code_counts == sorted(code_counts, reverse=True)

    def test_filter_firm_type(self, client: TestClient):
        body = client.get(
            "/api/vendors/list?firm_type=contractor"
        ).json()
        assert body["total"] == 2
        for row in body["items"]:
            assert row["firm_type"] == "contractor"

    def test_filter_contact_status_complete(self, client: TestClient):
        body = client.get(
            "/api/vendors/list?contact_status=complete"
        ).json()
        assert body["total"] == 2
        names = {r["name"] for r in body["items"]}
        assert names == {"Acme Concrete Co", "VanCon Self"}

    def test_filter_contact_status_empty(self, client: TestClient):
        body = client.get(
            "/api/vendors/list?contact_status=empty"
        ).json()
        assert body["total"] == 1
        assert body["items"][0]["name"] is None

    def test_filter_coding_uncoded(self, client: TestClient):
        body = client.get(
            "/api/vendors/list?coding_status=uncoded"
        ).json()
        # Precision + null-name row
        assert body["total"] == 2

    def test_filter_division(self, client: TestClient):
        body = client.get("/api/vendors/list?division=03").json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "Acme Concrete Co"

    def test_filter_division_no_match(self, client: TestClient):
        body = client.get("/api/vendors/list?division=99").json()
        assert body["total"] == 0

    def test_search_matches_name(self, client: TestClient):
        body = client.get("/api/vendors/list?search=bluestone").json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "BlueStone Masonry"

    def test_search_matches_email(self, client: TestClient):
        body = client.get("/api/vendors/list?search=acme.test").json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "Acme Concrete Co"

    def test_search_matches_code_substring(self, client: TestClient):
        body = client.get("/api/vendors/list?search=electrical").json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "Rocky Mtn Supply"

    def test_page_size_slicing(self, client: TestClient):
        body = client.get("/api/vendors/list?page=2&page_size=2").json()
        assert body["total"] == 6
        assert body["page"] == 2
        assert body["page_size"] == 2
        assert len(body["items"]) == 2


# --------------------------------------------------------------------------- #
# /{vendor_id}                                                                #
# --------------------------------------------------------------------------- #


class TestDetail:
    def test_fetch_by_normalized_name(self, client: TestClient):
        resp = client.get("/api/vendors/Acme Concrete Co")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Acme Concrete Co"
        assert body["firm_type"] == "contractor"
        assert body["code_count"] == 3
        assert sorted(body["divisions"]) == ["03"]
        assert body["primary_division"] == "03"
        assert body["contact_status"] == "complete"
        assert body["coding_status"] == "coded"

    def test_fetch_whitespace_tolerant(self, client: TestClient):
        # Vendor IDs are the normalized name; path-converter preserves
        # spaces in the URL, and _norm_name collapses on the way in.
        resp = client.get("/api/vendors/  Acme   Concrete   Co  ")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Acme Concrete Co"

    def test_detail_multi_division_vendor(self, client: TestClient):
        resp = client.get("/api/vendors/BlueStone Masonry")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code_count"] == 2
        assert body["divisions"] == ["04"]
        assert body["contact_status"] == "partial"

    def test_detail_empty_row_uses_synthetic_id(self, client: TestClient):
        # First, find the null-name row's id from /list.
        listing = client.get(
            "/api/vendors/list?contact_status=empty"
        ).json()
        empty_id = listing["items"][0]["id"]
        assert empty_id.startswith("__empty__")

        resp = client.get(f"/api/vendors/{empty_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] is None
        assert body["firm_type"] == "unknown"
        assert body["coding_status"] == "uncoded"

    def test_unknown_id_returns_404(self, client: TestClient):
        resp = client.get("/api/vendors/Does Not Exist")
        assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# /enrichments/{vendor_id}                                                    #
# --------------------------------------------------------------------------- #


class TestEnrichment:
    def test_enrichment_write_returns_merged_detail(self, client: TestClient):
        resp = client.post(
            "/api/vendors/enrichments/Precision Surveyors",
            json={
                "contact": "Paula Planner",
                "title": "Estimator",
                "email": "paula@precision.test",
                "phone": "555-0199",
                "firm_type": "supplier",
                "codes": [
                    "0330-Cast-in-place Concrete",
                    "0330-Cast-in-place Concrete",
                    "3100-Earthwork",
                ],
                "notes": "Confirmed by procurement.",
            },
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "Precision Surveyors"
        assert body["firm_type"] == "supplier"
        assert body["contact"] == "Paula Planner"
        assert body["email"] == "paula@precision.test"
        assert body["phone"] == "555-0199"
        assert body["codes"] == [
            "0330-Cast-in-place Concrete",
            "3100-Earthwork",
        ]
        assert body["contact_status"] == "complete"
        assert body["coding_status"] == "coded"
        assert body["enriched"] is True
        assert body["enrichment_notes"] == "Confirmed by procurement."

    def test_enrichment_read_back_updates_list_and_summary(
        self, client: TestClient,
    ):
        client.post(
            "/api/vendors/enrichments/Precision Surveyors",
            json={
                "contact": "Paula Planner",
                "email": "paula@precision.test",
                "phone": "555-0199",
                "firm_type": "supplier",
                "codes": ["3100-Earthwork"],
            },
        )

        summary = client.get("/api/vendors/summary").json()
        assert summary["complete_contact"] == 3
        assert summary["uncoded_vendors"] == 1
        assert summary["suppliers"] == 2
        assert summary["services"] == 0

        listing = client.get(
            "/api/vendors/list?search=precision"
        ).json()
        assert listing["total"] == 1
        row = listing["items"][0]
        assert row["contact_status"] == "complete"
        assert row["coding_status"] == "coded"
        assert row["enriched"] is True
        assert row["codes"] == ["3100-Earthwork"]

    def test_empty_enrichment_payload_returns_400(self, client: TestClient):
        resp = client.post(
            "/api/vendors/enrichments/Precision Surveyors",
            json={},
        )
        assert resp.status_code == 400

    def test_unknown_vendor_returns_404(self, client: TestClient):
        resp = client.post(
            "/api/vendors/enrichments/Does Not Exist",
            json={"email": "nobody@example.test"},
        )
        assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# /insights                                                                   #
# --------------------------------------------------------------------------- #


class TestInsights:
    def test_firm_type_breakdown(self, client: TestClient):
        body = client.get("/api/vendors/insights").json()
        fb = body["firm_type_breakdown"]
        assert fb["supplier"] == 1
        assert fb["contractor"] == 2
        assert fb["service"] == 1
        assert fb["internal"] == 1
        assert fb["unknown"] == 1

    def test_contact_health_breakdown(self, client: TestClient):
        body = client.get("/api/vendors/insights").json()
        ch = body["contact_health"]
        # Complete: Acme + VanCon = 2
        assert ch["complete"] == 2
        # Partial: Rocky (contact only), BlueStone (email only) = 2
        assert ch["partial"] == 2
        # Minimal: Precision (name only) = 1
        assert ch["minimal"] == 1
        # Empty: null-name row = 1
        assert ch["empty"] == 1

    def test_coding_breakdown(self, client: TestClient):
        body = client.get("/api/vendors/insights").json()
        cb = body["coding_breakdown"]
        assert cb["coded"] == 4
        assert cb["uncoded"] == 2

    def test_top_codes(self, client: TestClient):
        body = client.get("/api/vendors/insights").json()
        # Every code in the seed is unique (each appears exactly once)
        # so order is insertion-ordered by Counter. Check size matches.
        codes = body["top_codes"]
        assert len(codes) == 7
        for row in codes:
            assert row["vendor_count"] == 1

    def test_top_divisions(self, client: TestClient):
        body = client.get("/api/vendors/insights").json()
        # Divisions by vendor_count:
        #   03: Acme (1 vendor, 3 code occurrences)
        #   04: BlueStone (1, 2)
        #   01: VanCon (1, 1)
        #   26: Rocky (1, 1)
        divisions = {r["division"]: r for r in body["top_divisions"]}
        assert set(divisions.keys()) == {"01", "03", "04", "26"}
        assert divisions["03"]["vendor_count"] == 1
        assert divisions["03"]["code_count"] == 3
        assert divisions["04"]["code_count"] == 2
        assert divisions["01"]["code_count"] == 1
        assert divisions["26"]["code_count"] == 1

    def test_thin_divisions(self, client: TestClient):
        # Default thin_division_max=2 → every division (each has vendor_count=1) surfaces
        body = client.get("/api/vendors/insights").json()
        thin = {r["division"] for r in body["thin_divisions"]}
        assert thin == {"01", "03", "04", "26"}

    def test_thin_divisions_tighter_threshold(self, client: TestClient):
        # thin_division_max=0 → nothing surfaces (everything has >= 1 vendor)
        body = client.get(
            "/api/vendors/insights?thin_division_max=0"
        ).json()
        assert body["thin_divisions"] == []

    def test_depth_leaders(self, client: TestClient):
        body = client.get("/api/vendors/insights").json()
        leaders = body["depth_leaders"]
        # Only Acme (3 codes) and BlueStone (2 codes) meet the >=2-code gate
        assert len(leaders) == 2
        assert leaders[0]["name"] == "Acme Concrete Co"
        assert leaders[0]["code_count"] == 3
        assert leaders[1]["name"] == "BlueStone Masonry"
        assert leaders[1]["code_count"] == 2

    def test_top_n_caps_codes(self, client: TestClient):
        body = client.get("/api/vendors/insights?top_n=3").json()
        assert len(body["top_codes"]) == 3
        # Divisions list is only 4 total, but capped at 3 also.
        assert len(body["top_divisions"]) == 3

    def test_recommendation_context_reflects_enrichment(
        self,
        client: TestClient,
        seeded_engine: Engine,
        seeded_tenant_id: str,
    ):
        client.post(
            "/api/vendors/enrichments/Precision Surveyors",
            json={
                "contact": "Paula Planner",
                "email": "paula@precision.test",
                "phone": "555-0199",
                "codes": ["3100-Earthwork"],
            },
        )

        context = vendors_insights._build_data_context(
            seeded_engine, seeded_tenant_id,
        )
        assert context["contact_health"]["minimal"] == 0
        assert context["contact_health"]["complete"] == 3
        assert context["coding_breakdown"]["uncoded"] == 1
