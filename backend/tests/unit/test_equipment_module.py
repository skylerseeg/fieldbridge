"""Tests for app.modules.equipment.

Strategy:
  1. Build a fresh SQLite DB per test via fixtures.
  2. Import ``app.services.excel_marts`` so every mart Table is registered
     on Base.metadata, then create_all() builds the real schema.
  3. Seed 4 fake assets, one per utilization bucket, plus a rental row.
  4. Drive the API through ``fastapi.testclient.TestClient``, overriding
     the engine + tenant_id dependencies so the router talks to our
     seeded test DB instead of the process-wide default.

The seed is deliberately small — we're asserting on exact bucket counts
(``{under: 1, excessive: 1, good: 1, issues: 1}``), which makes a
regression in classify_bucket impossible to miss.
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
from app.modules.equipment.router import (
    _default_engine,
    get_engine,
    get_tenant_id,
    router as equipment_router,
)
from app.modules.equipment.schema import UtilizationBucket
from app.modules.equipment.service import classify_bucket


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


# Pinned at import time, but relative to real UTC — because the service
# classifies buckets against wall-clock ``datetime.now()`` and we don't want
# tests to bit-rot into the "issues" bucket as the calendar advances. A
# single-session pin keeps the seed deterministic within a pytest run.
# Naive so the SQLite-stored (naive) ticket_date values compare cleanly.
NOW = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


@pytest.fixture
def seeded_engine(tmp_path) -> Engine:
    """SQLite file with every mart schema + our four canonical assets."""
    url = f"sqlite:///{tmp_path / 'equipment_test.db'}"
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

    # --- utilization tickets ------------------------------------------------
    # excessive: 60 tickets across 7 days -> ~60/week
    excessive_rows = [
        (
            tenant_id,
            (NOW - timedelta(days=6 - (i % 7))).isoformat(),
            f"EX-{i}",
            "TRUCK-EXCESSIVE",
            "job-ex",
            8.0,
            "hrs",
            100.0,
            800.0,
        )
        for i in range(60)
    ]
    # good: 15 tickets across 7 days -> ~15/week
    good_rows = [
        (
            tenant_id,
            (NOW - timedelta(days=6 - (i % 7))).isoformat(),
            f"GD-{i}",
            "TRUCK-GOOD",
            "job-gd",
            6.0,
            "hrs",
            90.0,
            540.0,
        )
        for i in range(15)
    ]
    # under: 3 tickets across 30 days -> ~0.7/week
    under_rows = [
        (
            tenant_id,
            (NOW - timedelta(days=29 - i * 10)).isoformat(),
            f"UN-{i}",
            "TRUCK-UNDER",
            "job-un",
            4.0,
            "HOURS",
            80.0,
            320.0,
        )
        for i in range(3)
    ]
    # issues: 5 tickets but the asset is retired in the asset master.
    issues_rows = [
        (
            tenant_id,
            (NOW - timedelta(days=6 - i)).isoformat(),
            f"IS-{i}",
            "TRUCK-ISSUES",
            "job-is",
            2.0,
            "hrs",
            50.0,
            100.0,
        )
        for i in range(5)
    ]

    insert_ticket = text(
        """
        INSERT INTO mart_equipment_utilization
            (tenant_id, ticket_date, ticket, truck, job,
             qty, units, price, extended_price)
        VALUES (:tenant_id, :ticket_date, :ticket, :truck, :job,
                :qty, :units, :price, :extended_price)
        """
    )

    with engine.begin() as conn:
        for row in excessive_rows + good_rows + under_rows + issues_rows:
            conn.execute(
                insert_ticket,
                {
                    "tenant_id": row[0],
                    "ticket_date": row[1],
                    "ticket": row[2],
                    "truck": row[3],
                    "job": row[4],
                    "qty": row[5],
                    "units": row[6],
                    "price": row[7],
                    "extended_price": row[8],
                },
            )

        # Retire TRUCK-ISSUES so it's forced into the issues bucket. We
        # store the barcode as the raw truck name in a companion row; the
        # service looks up asset master by truck name -> retired_date.
        conn.execute(
            text(
                """
                INSERT INTO mart_asset_barcodes
                    (tenant_id, barcode, manufacturer, model, material,
                     retired_date)
                VALUES (:tenant_id, :barcode, :manufacturer, :model,
                        :material, :retired_date)
                """
            ),
            {
                "tenant_id": tenant_id,
                # asset_barcodes uses integer barcode PK; lookups in service
                # key on str(barcode) vs truck name, so we use a numeric
                # sentinel and also insert a retired-date-only master via
                # direct UPDATE to correlate by truck. The service's
                # asset_master dict maps str(barcode) -> retired_date; since
                # our trucks are named strings, retirement has to be
                # signalled via an explicit last-ticket-date >= 60 days ago.
                # See below — we force TRUCK-ISSUES old with an extra
                # stale ticket to hit the "issues" path without depending
                # on barcode join.
                "barcode": 1,
                "manufacturer": "Test",
                "model": "Mk1",
                "material": "steel",
                "retired_date": (NOW - timedelta(days=30)).isoformat(),
            },
        )

        # Force TRUCK-ISSUES to look stale: add one ticket 90 days ago and
        # REMOVE any recent tickets for it so its last_ticket is stale.
        conn.execute(
            text(
                "DELETE FROM mart_equipment_utilization "
                "WHERE tenant_id = :tid AND truck = 'TRUCK-ISSUES'"
            ),
            {"tid": tenant_id},
        )
        conn.execute(
            insert_ticket,
            {
                "tenant_id": tenant_id,
                "ticket_date": (NOW - timedelta(days=90)).isoformat(),
                "ticket": "IS-STALE",
                "truck": "TRUCK-ISSUES",
                "job": "job-is",
                "qty": 2.0,
                "units": "hrs",
                "price": 50.0,
                "extended_price": 100.0,
            },
        )

        # Mark TRUCK-GOOD as a rental so ownership metrics have both sides.
        conn.execute(
            text(
                """
                INSERT INTO mart_equipment_rentals
                    (tenant_id, equipment, rental_company, picked_up_date,
                     rate, rate_unit)
                VALUES (:tenant_id, 'TRUCK-GOOD', 'AcmeRent',
                        :picked_up_date, :rate, 'week')
                """
            ),
            {
                "tenant_id": tenant_id,
                "picked_up_date": (NOW - timedelta(days=10)).isoformat(),
                "rate": 1500.0,
            },
        )

        # Status board context: current emwo job and latest transfer.
        conn.execute(
            text(
                """
                INSERT INTO mart_work_orders
                    (tenant_id, work_order, equipment, description, status,
                     open_date, job_number)
                VALUES
                    (:tenant_id, 'WO-100', 'TRUCK-UNDER',
                     'Hydraulic leak check', 'O', :open_date, '24-104'),
                    (:tenant_id, 'WO-200', 'TRUCK-IDLE',
                     'Idle unit field check', 'H', :open_date, '24-205')
                """
            ),
            {
                "tenant_id": tenant_id,
                "open_date": (NOW - timedelta(days=2)).isoformat(),
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO mart_equipment_transfers
                    (tenant_id, id, transfer_date, tool_consumable, location,
                     quantity, requested_by, user)
                VALUES
                    (:tenant_id, 1, :transfer_date, 'TRUCK-UNDER',
                     'Yard B', 1, 'Foreman A', 'Dispatcher B')
                """
            ),
            {
                "tenant_id": tenant_id,
                "transfer_date": (NOW - timedelta(days=1)).isoformat(),
            },
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
    """FastAPI TestClient wired to our seeded DB."""
    app = FastAPI()
    app.include_router(equipment_router, prefix="/api/equipment")

    app.dependency_overrides[get_engine] = lambda: seeded_engine
    app.dependency_overrides[get_tenant_id] = lambda: seeded_tenant_id

    # Also clear the process-wide engine cache so we never accidentally hit
    # the default settings DB if an override gets dropped.
    _default_engine.cache_clear()

    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# classify_bucket — pure function                                             #
# --------------------------------------------------------------------------- #


class TestClassifyBucket:
    def test_retired_is_always_issues(self):
        assert (
            classify_bucket(
                tickets=100,
                first_ticket=NOW - timedelta(days=7),
                last_ticket=NOW,
                retired_date=NOW - timedelta(days=1),
                now=NOW,
            )
            is UtilizationBucket.ISSUES
        )

    def test_stale_without_retirement_is_issues(self):
        assert (
            classify_bucket(
                tickets=3,
                first_ticket=NOW - timedelta(days=120),
                last_ticket=NOW - timedelta(days=90),
                retired_date=None,
                now=NOW,
            )
            is UtilizationBucket.ISSUES
        )

    def test_excessive_bucket(self):
        assert (
            classify_bucket(
                tickets=60,
                first_ticket=NOW - timedelta(days=6),
                last_ticket=NOW,
                retired_date=None,
                now=NOW,
            )
            is UtilizationBucket.EXCESSIVE
        )

    def test_under_bucket(self):
        assert (
            classify_bucket(
                tickets=3,
                first_ticket=NOW - timedelta(days=29),
                last_ticket=NOW,
                retired_date=None,
                now=NOW,
            )
            is UtilizationBucket.UNDER
        )

    def test_good_bucket(self):
        assert (
            classify_bucket(
                tickets=15,
                first_ticket=NOW - timedelta(days=6),
                last_ticket=NOW,
                retired_date=None,
                now=NOW,
            )
            is UtilizationBucket.GOOD
        )

    def test_zero_tickets_is_under(self):
        assert (
            classify_bucket(
                tickets=0,
                first_ticket=None,
                last_ticket=None,
                retired_date=None,
                now=NOW,
            )
            is UtilizationBucket.UNDER
        )


# --------------------------------------------------------------------------- #
# API endpoints                                                               #
# --------------------------------------------------------------------------- #


class TestSummary:
    def test_kpi_tiles(self, client: TestClient):
        resp = client.get("/api/equipment/summary")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        # Four canonical assets, one per bucket.
        assert body["total_assets"] == 4
        assert body["bucket_excessive"] == 1
        assert body["bucket_good"] == 1
        assert body["bucket_under"] == 1
        assert body["bucket_issues"] == 1

        # TRUCK-GOOD is rented.
        assert body["rented_assets"] == 1
        assert body["owned_assets"] == 3

        # 30-day window excludes the single 90-day-ago stale ticket.
        # excessive (60) + good (15) + under (3 recent in 30d) = 78
        assert body["tickets_30d"] == 78


class TestList:
    def test_pagination_and_total(self, client: TestClient):
        resp = client.get("/api/equipment/list?page=1&page_size=2")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 4
        assert body["page"] == 1
        assert body["page_size"] == 2
        assert len(body["items"]) == 2

        resp2 = client.get("/api/equipment/list?page=2&page_size=2")
        assert resp2.json()["page"] == 2
        assert len(resp2.json()["items"]) == 2

    def test_sort_by_tickets_desc(self, client: TestClient):
        resp = client.get("/api/equipment/list?sort_by=tickets&sort_dir=desc")
        items = resp.json()["items"]
        # excessive (60) > good (15) > under (3) > issues (1)
        assert items[0]["truck"] == "TRUCK-EXCESSIVE"
        assert items[0]["tickets"] == 60

    def test_filter_by_bucket(self, client: TestClient):
        resp = client.get("/api/equipment/list?bucket=excessive")
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["truck"] == "TRUCK-EXCESSIVE"
        assert items[0]["bucket"] == "excessive"

    def test_filter_by_ownership_rented(self, client: TestClient):
        resp = client.get("/api/equipment/list?ownership=rented")
        items = resp.json()["items"]
        assert {i["truck"] for i in items} == {"TRUCK-GOOD"}
        assert items[0]["ownership"] == "rented"

    def test_search_substring(self, client: TestClient):
        resp = client.get("/api/equipment/list?search=issues")
        items = resp.json()["items"]
        assert {i["truck"] for i in items} == {"TRUCK-ISSUES"}


class TestStatusBoard:
    def test_status_board_includes_emwo_job_and_transfer(self, client: TestClient):
        resp = client.get("/api/equipment/status?search=under")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["stale_threshold_days"] == 14
        assert body["total"] == 1

        item = body["items"][0]
        assert item["truck"] == "TRUCK-UNDER"
        assert item["bucket"] == "under"
        assert item["current_job"]["work_order"] == "WO-100"
        assert item["current_job"]["job_number"] == "24-104"
        assert item["current_job"]["status"] == "open"
        assert item["last_transfer"]["location"] == "Yard B"
        assert item["last_transfer"]["requested_by"] == "Foreman A"

    def test_status_board_stale_only_uses_14_day_ticket_lane(
        self, client: TestClient
    ):
        resp = client.get("/api/equipment/status?stale_only=true")
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]

        assert {i["truck"] for i in items} == {"TRUCK-IDLE", "TRUCK-ISSUES"}
        assert all(i["stale_ticket"] for i in items)


class TestDetail:
    def test_detail_has_recent_tickets_and_bucket(self, client: TestClient):
        resp = client.get("/api/equipment/TRUCK-EXCESSIVE")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "TRUCK-EXCESSIVE"
        assert body["bucket"] == "excessive"
        assert body["ownership"] == "owned"
        assert body["tickets"] == 60
        assert len(body["recent_tickets"]) == 10  # capped at recent_limit=10
        # cost_per_hour: revenue=60*800=48000, hours=60*8=480 -> 100/hr
        assert body["cost_per_hour"] == pytest.approx(100.0)

    def test_detail_returns_rental_fields_when_rented(self, client: TestClient):
        resp = client.get("/api/equipment/TRUCK-GOOD")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ownership"] == "rented"
        assert body["rental_company"] == "AcmeRent"
        assert body["rental_rate"] == 1500.0
        assert body["rate_unit"] == "week"

    def test_detail_404_on_unknown(self, client: TestClient):
        resp = client.get("/api/equipment/GHOST-TRUCK-99")
        assert resp.status_code == 404


class TestInsights:
    def test_bucket_breakdown_matches_screen(self, client: TestClient):
        resp = client.get("/api/equipment/insights")
        assert resp.status_code == 200
        body = resp.json()
        buckets = body["utilization_buckets"]
        assert buckets == {"under": 1, "excessive": 1, "good": 1, "issues": 1}

    def test_fuel_cost_per_hour_ordered_and_correct(self, client: TestClient):
        resp = client.get("/api/equipment/insights")
        fuel = resp.json()["fuel_cost_per_hour_by_asset"]

        # 4 assets have hour-denominated tickets.
        assert len(fuel) == 4
        # Sorted by hours logged descending -> EXCESSIVE first.
        assert fuel[0]["truck"] == "TRUCK-EXCESSIVE"
        # TRUCK-EXCESSIVE: revenue=48000, hours=480 -> 100/hr
        assert fuel[0]["cost_per_hour"] == pytest.approx(100.0)

        # TRUCK-GOOD: revenue=15*540=8100, hours=15*6=90 -> 90/hr
        good = next(f for f in fuel if f["truck"] == "TRUCK-GOOD")
        assert good["cost_per_hour"] == pytest.approx(90.0)

    def test_rental_vs_owned_counts(self, client: TestClient):
        resp = client.get("/api/equipment/insights")
        body = resp.json()["rental_vs_owned"]
        assert body["owned"]["count"] == 3   # excessive, under, issues
        assert body["rented"]["count"] == 1  # good
        assert body["rented"]["active_rentals"] == 1  # no returned_date
        assert body["rented"]["total_rate_committed"] == 1500.0
        # Owned revenue = excessive (48000) + under (960) + issues (100) = 49060
        assert body["owned"]["total_revenue"] == pytest.approx(49060.0)
