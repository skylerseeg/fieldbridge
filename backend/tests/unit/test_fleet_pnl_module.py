"""Tests for app.modules.fleet_pnl.

Strategy mirrors the other mart-backed modules:
  1. Fresh SQLite DB per test via fixtures.
  2. Register every mart Table against Base.metadata, create_all().
  3. Seed four canonical trucks spanning every combination of
     ownership / invoice / utilization buckets, plus a handful of
     rental-in contracts so the rental summary has real numbers.
  4. Drive the API through TestClient with dependency overrides.

Canonical seed (ticket counts chosen so the (3, 10) threshold pair
splits the buckets cleanly):

  TK-HEAVY  owned    12 tickets  all invoiced      heavy   JOB-A  Sand/BigSand
  TK-MED    owned     6 tickets  3/3 split         healthy JOB-B  Gravel/QuarryCo
  TK-LOW    lessor    2 tickets  all uninvoiced    under   JOB-A  Sand/BigSand
  TK-SOLO   owned     1 ticket   uninvoiced        under   JOB-C  Sand/BigSand

Plus three rental-in contracts (Sunbelt x2 monthly+hourly, Wheeler
x1 monthly RPO returned).
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
from app.modules.fleet_pnl.router import (
    _default_engine,
    get_engine,
    get_tenant_id,
    router as fleet_router,
)
from app.modules.fleet_pnl.service import _strip_job_key


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


NOW = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


@pytest.fixture
def seeded_engine(tmp_path) -> Engine:
    url = f"sqlite:///{tmp_path / 'fleet_pnl_test.db'}"
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

    # -- Truck recipes ----------------------------------------------------
    # Each recipe spawns ``count`` tickets stamped 1..count days back.
    truck_recipes = [
        {
            "truck": "TK-HEAVY",
            "count": 12,
            "invoiced": [True] * 12,
            "is_lessor": False,
            "job": " JOB-A",   # leading space on purpose — Vista quirk
            "vendor": "BigSand",
            "material": "Sand",
            "driver": "DriverA",
            "price": 10.0,
            "qty": 10.0,
            "extended_price": 100.0,
        },
        {
            "truck": "TK-MED",
            "count": 6,
            "invoiced": [True, True, True, False, False, False],
            "is_lessor": False,
            "job": "JOB-B",
            "vendor": "QuarryCo",
            "material": "Gravel",
            "driver": "DriverB",
            "price": 5.0,
            "qty": 5.0,
            "extended_price": 50.0,
        },
        {
            "truck": "TK-LOW",
            "count": 2,
            "invoiced": [False, False],
            "is_lessor": True,
            "job": "JOB-A",
            "vendor": "BigSand",
            "material": "Sand",
            "driver": "DriverC",
            "price": 4.0,
            "qty": 3.0,
            "extended_price": 40.0,
        },
        {
            "truck": "TK-SOLO",
            "count": 1,
            "invoiced": [False],
            "is_lessor": False,
            "job": "JOB-C",
            "vendor": "BigSand",
            "material": "Sand",
            "driver": "DriverA",
            "price": 2.5,
            "qty": 2.0,
            "extended_price": 25.0,
        },
    ]

    util_rows: list[dict] = []
    seq = 1000  # monotonically increasing ticket number
    for rec in truck_recipes:
        for i in range(rec["count"]):
            util_rows.append(
                {
                    "ticket_date": _iso(NOW - timedelta(days=i + 1)),
                    "ticket": str(seq),
                    "truck": rec["truck"],
                    "job": rec["job"],
                    "images": None,
                    "is_lessor": rec["is_lessor"],
                    "invoiced": rec["invoiced"][i],
                    "invoice_number": (
                        f"INV-{seq}" if rec["invoiced"][i] else None
                    ),
                    "invoice_date": (
                        _iso(NOW - timedelta(days=i))
                        if rec["invoiced"][i] else None
                    ),
                    "price": rec["price"],
                    "extended_price": rec["extended_price"],
                    "vendor": rec["vendor"],
                    "pit": "Willow Creek Pit",
                    "material": rec["material"],
                    "trailer_1": None,
                    "trailer_2": None,
                    "qty": rec["qty"],
                    "units": "Tons",
                    "driver": rec["driver"],
                    "notes": None,
                }
            )
            seq += 1

    insert_util = text(
        """
        INSERT INTO mart_equipment_utilization
            (tenant_id, ticket_date, ticket, truck, job, images,
             is_lessor, invoiced, invoice_number, invoice_date,
             price, extended_price, vendor, pit, material,
             trailer_1, trailer_2, qty, units, driver, notes)
        VALUES (:tenant_id, :ticket_date, :ticket, :truck, :job, :images,
                :is_lessor, :invoiced, :invoice_number, :invoice_date,
                :price, :extended_price, :vendor, :pit, :material,
                :trailer_1, :trailer_2, :qty, :units, :driver, :notes)
        """
    )

    # -- Rental-in contracts ---------------------------------------------
    rental_rows = [
        {
            "equipment": "Heaters",
            "rental_company": "Sunbelt Rentals, Inc",
            "picked_up_date": _iso(NOW - timedelta(days=60)),
            "images": None,
            "job": " JOB-A",
            "rented_by": "Alice",
            "picked_up_by": "Alice",
            "scheduled_return_date": _iso(NOW + timedelta(days=30)),
            "returned_date": None,                # active
            "maintained_by": True,
            "rental_length": "> Month",
            "rate": 2500.0,
            "rate_unit": "Monthly",
            "hours_start": None,
            "hours_end": None,
            "serial_number": None,
            "is_rpo": False,
        },
        {
            "equipment": "Cat 950 Loader",
            "rental_company": "Wheeler Machinery Co.",
            "picked_up_date": _iso(NOW - timedelta(days=120)),
            "images": None,
            "job": "JOB-B",
            "rented_by": "Bob",
            "picked_up_by": "Bob",
            "scheduled_return_date": _iso(NOW - timedelta(days=30)),
            "returned_date": _iso(NOW - timedelta(days=25)),  # returned
            "maintained_by": True,
            "rental_length": "> Month",
            "rate": 10000.0,
            "rate_unit": "Monthly",
            "hours_start": None,
            "hours_end": None,
            "serial_number": None,
            "is_rpo": True,
        },
        {
            "equipment": "Small Pump",
            "rental_company": "Sunbelt Rentals, Inc",
            "picked_up_date": _iso(NOW - timedelta(days=10)),
            "images": None,
            "job": "JOB-C",
            "rented_by": "Alice",
            "picked_up_by": "Alice",
            "scheduled_return_date": _iso(NOW + timedelta(days=5)),
            "returned_date": None,                # active
            "maintained_by": True,
            "rental_length": "2 Weeks",
            "rate": 150.0,
            "rate_unit": "Hourly",
            "hours_start": None,
            "hours_end": None,
            "serial_number": None,
            "is_rpo": False,
        },
    ]

    insert_rental = text(
        """
        INSERT INTO mart_equipment_rentals
            (tenant_id, equipment, rental_company, picked_up_date, images,
             job, rented_by, picked_up_by, scheduled_return_date,
             returned_date, maintained_by, rental_length, rate, rate_unit,
             hours_start, hours_end, serial_number, is_rpo)
        VALUES (:tenant_id, :equipment, :rental_company, :picked_up_date,
                :images, :job, :rented_by, :picked_up_by,
                :scheduled_return_date, :returned_date, :maintained_by,
                :rental_length, :rate, :rate_unit, :hours_start, :hours_end,
                :serial_number, :is_rpo)
        """
    )

    with engine.begin() as conn:
        for u in util_rows:
            conn.execute(insert_util, {"tenant_id": tenant_id, **u})
        for r in rental_rows:
            conn.execute(insert_rental, {"tenant_id": tenant_id, **r})

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
    app.include_router(fleet_router, prefix="/api/fleet-pnl")

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
        assert _strip_job_key(" JOB-A") == "JOB-A"

    def test_collapses_internal_whitespace(self):
        assert _strip_job_key("  JOB   X  ") == "JOB X"

    def test_empty_string_returns_none(self):
        assert _strip_job_key("") is None
        assert _strip_job_key("   ") is None

    def test_none_returns_none(self):
        assert _strip_job_key(None) is None


# --------------------------------------------------------------------------- #
# /summary                                                                    #
# --------------------------------------------------------------------------- #


class TestSummary:
    def test_kpi_tiles(self, client: TestClient):
        resp = client.get("/api/fleet-pnl/summary")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        # 4 distinct trucks, 12+6+2+1 = 21 tickets.
        assert body["total_trucks"] == 4
        assert body["total_tickets"] == 21

        # Revenue totals: 12*100 + 6*50 + 2*40 + 1*25 = 1605.
        assert body["total_revenue"] == pytest.approx(1605.0)

        # Invoiced: TK-HEAVY all (12*100=1200) + TK-MED 3 (3*50=150) = 1350.
        assert body["invoiced_revenue"] == pytest.approx(1350.0)
        # Uninvoiced: 3*50 + 2*40 + 1*25 = 150 + 80 + 25 = 255.
        assert body["uninvoiced_revenue"] == pytest.approx(255.0)

        # invoice_rate = 15/21 ≈ 0.7143.
        assert body["invoice_rate"] == pytest.approx(15 / 21)

        # Ownership: 3 owned, 1 lessor, 0 mixed/unknown.
        assert body["owned_trucks"] == 3
        assert body["lessor_trucks"] == 1
        assert body["mixed_trucks"] == 0
        assert body["unknown_ownership_trucks"] == 0

        # Breadth: 3 distinct jobs (A/B/C), 2 vendors (BigSand/QuarryCo),
        # 3 drivers (A/B/C).
        assert body["unique_jobs"] == 3
        assert body["unique_vendors"] == 2
        assert body["unique_drivers"] == 3

        # Rental-in: 3 contracts total, monthly = 2500 + 10000 = 12500.
        assert body["rental_contracts"] == 3
        assert body["rental_monthly_cost"] == pytest.approx(12_500.0)

        # qty: 12*10 + 6*5 + 2*3 + 1*2 = 120 + 30 + 6 + 2 = 158.
        assert body["total_qty"] == pytest.approx(158.0)


# --------------------------------------------------------------------------- #
# /list                                                                       #
# --------------------------------------------------------------------------- #


class TestList:
    def test_pagination_and_default_sort(self, client: TestClient):
        resp = client.get("/api/fleet-pnl/list")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 4
        # Default sort = revenue desc: HEAVY > MED > LOW > SOLO.
        assert [i["id"] for i in body["items"]] == [
            "TK-HEAVY", "TK-MED", "TK-LOW", "TK-SOLO",
        ]

    def test_filter_lessor_flag(self, client: TestClient):
        resp = client.get("/api/fleet-pnl/list?lessor_flag=lessor")
        ids = {i["id"] for i in resp.json()["items"]}
        assert ids == {"TK-LOW"}

        resp = client.get("/api/fleet-pnl/list?lessor_flag=owned")
        ids = {i["id"] for i in resp.json()["items"]}
        assert ids == {"TK-HEAVY", "TK-MED", "TK-SOLO"}

    def test_filter_invoice_bucket(self, client: TestClient):
        resp = client.get(
            "/api/fleet-pnl/list?invoice_bucket=fully_invoiced"
        )
        ids = {i["id"] for i in resp.json()["items"]}
        assert ids == {"TK-HEAVY"}

        resp = client.get(
            "/api/fleet-pnl/list?invoice_bucket=partially_invoiced"
        )
        ids = {i["id"] for i in resp.json()["items"]}
        assert ids == {"TK-MED"}

        resp = client.get(
            "/api/fleet-pnl/list?invoice_bucket=uninvoiced"
        )
        ids = {i["id"] for i in resp.json()["items"]}
        assert ids == {"TK-LOW", "TK-SOLO"}

    def test_filter_utilization_bucket_with_custom_thresholds(
        self, client: TestClient,
    ):
        # With (3, 10): HEAVY(12)=heavy, MED(6)=healthy,
        # LOW(2)=under, SOLO(1)=under.
        resp = client.get(
            "/api/fleet-pnl/list"
            "?underutilized_max_tickets=3&heavily_utilized_min_tickets=10"
            "&utilization_bucket=heavily_utilized"
        )
        ids = {i["id"] for i in resp.json()["items"]}
        assert ids == {"TK-HEAVY"}

        resp = client.get(
            "/api/fleet-pnl/list"
            "?underutilized_max_tickets=3&heavily_utilized_min_tickets=10"
            "&utilization_bucket=healthy"
        )
        ids = {i["id"] for i in resp.json()["items"]}
        assert ids == {"TK-MED"}

        resp = client.get(
            "/api/fleet-pnl/list"
            "?underutilized_max_tickets=3&heavily_utilized_min_tickets=10"
            "&utilization_bucket=underutilized"
        )
        ids = {i["id"] for i in resp.json()["items"]}
        assert ids == {"TK-LOW", "TK-SOLO"}

    def test_search_matches_top_vendor(self, client: TestClient):
        resp = client.get("/api/fleet-pnl/list?search=quarry")
        ids = {i["id"] for i in resp.json()["items"]}
        # Only TK-MED's top_vendor contains "quarry".
        assert ids == {"TK-MED"}

    def test_search_matches_truck_tag(self, client: TestClient):
        resp = client.get("/api/fleet-pnl/list?search=solo")
        ids = {i["id"] for i in resp.json()["items"]}
        assert ids == {"TK-SOLO"}

    def test_sort_by_uninvoiced_revenue_desc(self, client: TestClient):
        resp = client.get(
            "/api/fleet-pnl/list?sort_by=uninvoiced_revenue&sort_dir=desc"
        )
        ids = [i["id"] for i in resp.json()["items"]]
        # TK-MED 150, TK-LOW 80, TK-SOLO 25, TK-HEAVY 0.
        assert ids == ["TK-MED", "TK-LOW", "TK-SOLO", "TK-HEAVY"]

    def test_sort_by_ticket_count_asc(self, client: TestClient):
        resp = client.get(
            "/api/fleet-pnl/list?sort_by=ticket_count&sort_dir=asc"
        )
        ids = [i["id"] for i in resp.json()["items"]]
        assert ids == ["TK-SOLO", "TK-LOW", "TK-MED", "TK-HEAVY"]

    def test_row_fields_populated(self, client: TestClient):
        resp = client.get("/api/fleet-pnl/list?sort_by=truck&sort_dir=asc")
        rows = {i["id"]: i for i in resp.json()["items"]}

        heavy = rows["TK-HEAVY"]
        assert heavy["ticket_count"] == 12
        assert heavy["revenue"] == pytest.approx(1200.0)
        assert heavy["invoiced_count"] == 12
        assert heavy["invoice_rate"] == pytest.approx(1.0)
        assert heavy["lessor_flag"] == "owned"
        assert heavy["invoice_bucket"] == "fully_invoiced"
        # top_job is stripped (" JOB-A" -> "JOB-A").
        assert heavy["top_job"] == "JOB-A"
        assert heavy["top_vendor"] == "BigSand"
        assert heavy["top_material"] == "Sand"
        assert heavy["top_driver"] == "DriverA"
        assert heavy["jobs_served"] == 1
        assert heavy["vendors_served"] == 1


# --------------------------------------------------------------------------- #
# /{truck_id}                                                                 #
# --------------------------------------------------------------------------- #


class TestDetail:
    def test_detail_heavy_has_mixes_and_recent(self, client: TestClient):
        resp = client.get("/api/fleet-pnl/TK-HEAVY")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["id"] == "TK-HEAVY"
        assert body["ticket_count"] == 12
        assert body["revenue"] == pytest.approx(1200.0)
        # Default recent_limit is 20; we only have 12 tickets.
        assert len(body["recent_tickets"]) == 12
        # Newest first — first recent ticket's date > last recent's.
        first = body["recent_tickets"][0]["ticket_date"]
        last = body["recent_tickets"][-1]["ticket_date"]
        assert first > last

        # Mix rows (mix_limit default 5).
        assert len(body["vendor_mix"]) == 1
        assert body["vendor_mix"][0]["label"] == "BigSand"
        assert body["vendor_mix"][0]["ticket_count"] == 12
        assert body["vendor_mix"][0]["revenue"] == pytest.approx(1200.0)

        # job_mix strips the leading space.
        assert body["job_mix"][0]["label"] == "JOB-A"

    def test_detail_med_bucket_thresholds(self, client: TestClient):
        resp = client.get(
            "/api/fleet-pnl/TK-MED"
            "?underutilized_max_tickets=3&heavily_utilized_min_tickets=10"
        )
        body = resp.json()
        assert body["utilization_bucket"] == "healthy"
        assert body["invoice_bucket"] == "partially_invoiced"
        # invoiced_count 3 / 6 -> 0.5.
        assert body["invoice_rate"] == pytest.approx(0.5)

    def test_detail_lessor_and_uninvoiced(self, client: TestClient):
        resp = client.get("/api/fleet-pnl/TK-LOW")
        body = resp.json()
        assert body["lessor_flag"] == "lessor"
        assert body["invoice_bucket"] == "uninvoiced"
        assert body["invoiced_count"] == 0
        assert body["uninvoiced_revenue"] == pytest.approx(80.0)

    def test_detail_monthly_series_non_empty(self, client: TestClient):
        resp = client.get("/api/fleet-pnl/TK-HEAVY")
        body = resp.json()
        # 12 tickets span at most 12 days so fall in 1 or 2 calendar months.
        assert 1 <= len(body["monthly_series"]) <= 2
        total = sum(p["revenue"] for p in body["monthly_series"])
        assert total == pytest.approx(1200.0)

    def test_detail_404_on_unknown(self, client: TestClient):
        resp = client.get("/api/fleet-pnl/NOPE")
        assert resp.status_code == 404

    def test_detail_respects_recent_limit(self, client: TestClient):
        resp = client.get("/api/fleet-pnl/TK-HEAVY?recent_limit=3")
        body = resp.json()
        assert len(body["recent_tickets"]) == 3


# --------------------------------------------------------------------------- #
# /insights                                                                   #
# --------------------------------------------------------------------------- #


class TestInsights:
    def test_utilization_breakdown_with_thresholds(self, client: TestClient):
        resp = client.get(
            "/api/fleet-pnl/insights"
            "?underutilized_max_tickets=3&heavily_utilized_min_tickets=10"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["utilization_breakdown"] == {
            "idle": 0,
            "underutilized": 2,  # TK-LOW (2), TK-SOLO (1)
            "healthy": 1,        # TK-MED (6)
            "heavily_utilized": 1,  # TK-HEAVY (12)
        }
        # Tunables echo back.
        assert body["underutilized_max_tickets"] == 3
        assert body["heavily_utilized_min_tickets"] == 10

    def test_invoice_breakdown(self, client: TestClient):
        resp = client.get("/api/fleet-pnl/insights")
        body = resp.json()
        assert body["invoice_breakdown"] == {
            "fully_invoiced": 1,    # TK-HEAVY
            "partially_invoiced": 1,  # TK-MED
            "uninvoiced": 2,        # TK-LOW, TK-SOLO
            "unknown": 0,
        }

    def test_top_revenue(self, client: TestClient):
        resp = client.get("/api/fleet-pnl/insights")
        body = resp.json()
        rows = body["top_revenue"]
        assert [r["id"] for r in rows] == [
            "TK-HEAVY", "TK-MED", "TK-LOW", "TK-SOLO",
        ]
        assert rows[0]["value"] == pytest.approx(1200.0)

    def test_top_uninvoiced_excludes_zero(self, client: TestClient):
        resp = client.get("/api/fleet-pnl/insights")
        body = resp.json()
        rows = body["top_uninvoiced"]
        # TK-HEAVY has 0 uninvoiced -> excluded.
        assert [r["id"] for r in rows] == ["TK-MED", "TK-LOW", "TK-SOLO"]
        assert rows[0]["value"] == pytest.approx(150.0)

    def test_top_underutilized_ascending_by_ticket_count(
        self, client: TestClient,
    ):
        resp = client.get("/api/fleet-pnl/insights")
        body = resp.json()
        rows = body["top_underutilized"]
        # Ascending ticket_count: SOLO(1) < LOW(2) < MED(6) < HEAVY(12).
        assert [r["id"] for r in rows] == [
            "TK-SOLO", "TK-LOW", "TK-MED", "TK-HEAVY",
        ]

    def test_top_vendors_by_revenue(self, client: TestClient):
        resp = client.get("/api/fleet-pnl/insights")
        body = resp.json()
        # BigSand: 1200+80+25 = 1305; QuarryCo: 300.
        rows = body["top_vendors"]
        assert rows[0]["label"] == "BigSand"
        assert rows[0]["revenue"] == pytest.approx(1305.0)
        assert rows[1]["label"] == "QuarryCo"
        assert rows[1]["revenue"] == pytest.approx(300.0)

    def test_top_materials_and_jobs(self, client: TestClient):
        resp = client.get("/api/fleet-pnl/insights")
        body = resp.json()

        # Sand: HEAVY(1200) + LOW(80) + SOLO(25) = 1305; Gravel: 300.
        mats = body["top_materials"]
        assert mats[0]["label"] == "Sand"
        assert mats[0]["revenue"] == pytest.approx(1305.0)

        # JOB-A (stripped): HEAVY(1200) + LOW(80) = 1280.
        # JOB-B: MED(300). JOB-C: SOLO(25).
        jobs = body["top_jobs"]
        assert jobs[0]["label"] == "JOB-A"
        assert jobs[0]["revenue"] == pytest.approx(1280.0)

    def test_rental_in_summary(self, client: TestClient):
        resp = client.get("/api/fleet-pnl/insights")
        body = resp.json()
        rental = body["rental_in"]
        assert rental["contracts"] == 3
        # Sunbelt-monthly (active), Sunbelt-hourly (active), Wheeler (returned).
        assert rental["active_contracts"] == 2
        assert rental["rpo_contracts"] == 1
        assert rental["total_monthly_cost"] == pytest.approx(12_500.0)
        assert rental["total_hourly_cost"] == pytest.approx(150.0)

        # top_rental_vendors ranked by contract count — Sunbelt first (2),
        # Wheeler second (1).
        labels = [v["label"] for v in rental["top_rental_vendors"]]
        assert labels[0] == "Sunbelt Rentals, Inc"
        assert labels[1] == "Wheeler Machinery Co."
        # Sunbelt monthly revenue on its top-vendor row = 2500 (hourly excluded).
        assert rental["top_rental_vendors"][0]["revenue"] == pytest.approx(
            2500.0
        )

    def test_top_n_caps_lists(self, client: TestClient):
        resp = client.get("/api/fleet-pnl/insights?top_n=1")
        body = resp.json()
        assert len(body["top_revenue"]) == 1
        assert body["top_revenue"][0]["id"] == "TK-HEAVY"
        assert len(body["top_vendors"]) == 1
        assert len(body["top_jobs"]) == 1
