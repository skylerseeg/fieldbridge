"""Tests for app.modules.work_orders.

Strategy mirrors the equipment-module tests:
  1. Fresh SQLite DB per test via fixtures.
  2. Import ``app.services.excel_marts`` so every mart Table is registered
     on Base.metadata, then create_all() builds the real schema.
  3. Seed five canonical WOs — one per state we care about (open+fresh,
     open+overdue, hold+overdue, closed+on-budget, closed+over-budget) —
     plus one with an unknown status code so the ``unknown`` bucket has
     a non-zero count.
  4. Drive the API through ``fastapi.testclient.TestClient``, overriding
     the engine + tenant_id dependencies.

Dates are anchored to ``NOW`` (real wall-clock, pinned at import) so the
age/overdue math is deterministic within a pytest run regardless of
calendar drift.
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
from app.modules.work_orders.router import (
    _default_engine,
    get_engine,
    get_tenant_id,
    router as work_orders_router,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


NOW = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)

# Canonical WO seed. Keyed by work_order number.
#
# WO-OPEN-FRESH  — open 10 days, not overdue, low cost vs budget.
# WO-OPEN-OLD    — open 45 days, overdue (> 30d default), over-budget.
# WO-HOLD-OLD    — hold 50 days, overdue, mid-range cost.
# WO-CLOSED-OK   — closed, lifespan 20 days, under budget.
# WO-CLOSED-OVER — closed, lifespan 40 days, way over budget.
# WO-UNKNOWN     — status code we don't recognize (future Vista code 'P').


def _iso(dt: datetime) -> str:
    return dt.isoformat()


@pytest.fixture
def seeded_engine(tmp_path) -> Engine:
    url = f"sqlite:///{tmp_path / 'work_orders_test.db'}"
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

    insert = text(
        """
        INSERT INTO mart_work_orders
            (tenant_id, work_order, equipment, description, status, priority,
             requested_by, open_date, closed_date, mechanic,
             labor_hours, parts_cost, total_cost, job_number,
             estimated_hours, estimated_cost)
        VALUES
            (:tenant_id, :work_order, :equipment, :description, :status,
             :priority, :requested_by, :open_date, :closed_date, :mechanic,
             :labor_hours, :parts_cost, :total_cost, :job_number,
             :estimated_hours, :estimated_cost)
        """
    )

    seed = [
        {
            "tenant_id": tenant_id,
            "work_order": "WO-OPEN-FRESH",
            "equipment": "TRUCK-01",
            "description": "Oil change",
            "status": "O",
            "priority": "3",
            "requested_by": "Alice",
            "open_date": _iso(NOW - timedelta(days=10)),
            "closed_date": None,
            "mechanic": "Bob",
            "labor_hours": 2.0,
            "parts_cost": 50.0,
            "total_cost": 150.0,
            "job_number": "JOB-100",
            "estimated_hours": 3.0,
            "estimated_cost": 300.0,
        },
        {
            "tenant_id": tenant_id,
            "work_order": "WO-OPEN-OLD",
            "equipment": "TRUCK-02",
            "description": "Transmission rebuild",
            "status": "O",
            "priority": "1",
            "requested_by": "Alice",
            "open_date": _iso(NOW - timedelta(days=45)),
            "closed_date": None,
            "mechanic": "Carol",
            "labor_hours": 40.0,
            "parts_cost": 3000.0,
            "total_cost": 7000.0,
            "job_number": "JOB-101",
            "estimated_hours": 30.0,
            "estimated_cost": 5000.0,
        },
        {
            "tenant_id": tenant_id,
            "work_order": "WO-HOLD-OLD",
            "equipment": "TRUCK-03",
            "description": "Waiting on parts",
            "status": "H",
            "priority": "2",
            "requested_by": "Dan",
            "open_date": _iso(NOW - timedelta(days=50)),
            "closed_date": None,
            "mechanic": "Carol",
            "labor_hours": 5.0,
            "parts_cost": 500.0,
            "total_cost": 750.0,
            "job_number": "JOB-102",
            "estimated_hours": 10.0,
            "estimated_cost": 1500.0,
        },
        {
            "tenant_id": tenant_id,
            "work_order": "WO-CLOSED-OK",
            "equipment": "TRUCK-04",
            "description": "Brake pads",
            "status": "C",
            "priority": "3",
            "requested_by": "Alice",
            "open_date": _iso(NOW - timedelta(days=30)),
            "closed_date": _iso(NOW - timedelta(days=10)),
            "mechanic": "Bob",
            "labor_hours": 4.0,
            "parts_cost": 200.0,
            "total_cost": 400.0,
            "job_number": "JOB-103",
            "estimated_hours": 5.0,
            "estimated_cost": 500.0,
        },
        {
            "tenant_id": tenant_id,
            "work_order": "WO-CLOSED-OVER",
            "equipment": "TRUCK-05",
            "description": "Engine replacement",
            "status": "C",
            "priority": "1",
            "requested_by": "Eve",
            "open_date": _iso(NOW - timedelta(days=60)),
            "closed_date": _iso(NOW - timedelta(days=20)),
            "mechanic": "Carol",
            "labor_hours": 80.0,
            "parts_cost": 8000.0,
            "total_cost": 15000.0,
            "job_number": "JOB-104",
            "estimated_hours": 50.0,
            "estimated_cost": 10000.0,
        },
        {
            "tenant_id": tenant_id,
            "work_order": "WO-UNKNOWN",
            "equipment": "TRUCK-06",
            "description": "Future Vista status",
            "status": "P",  # not in _STATUS_MAP
            "priority": "9",  # not in _PRIORITY_MAP
            "requested_by": "Eve",
            "open_date": _iso(NOW - timedelta(days=5)),
            "closed_date": None,
            "mechanic": None,
            "labor_hours": None,
            "parts_cost": None,
            "total_cost": None,
            "job_number": None,
            "estimated_hours": None,
            "estimated_cost": None,
        },
    ]

    with engine.begin() as conn:
        for row in seed:
            conn.execute(insert, row)

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
    app.include_router(work_orders_router, prefix="/api/work-orders")

    app.dependency_overrides[get_engine] = lambda: seeded_engine
    app.dependency_overrides[get_tenant_id] = lambda: seeded_tenant_id

    # Clear process-wide engine cache so we never accidentally hit the
    # default settings DB if an override gets dropped.
    _default_engine.cache_clear()

    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# /summary                                                                    #
# --------------------------------------------------------------------------- #


class TestSummary:
    def test_kpi_tiles(self, client: TestClient):
        resp = client.get("/api/work-orders/summary")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["total_work_orders"] == 6
        # O: WO-OPEN-FRESH, WO-OPEN-OLD
        assert body["open_count"] == 2
        # C: WO-CLOSED-OK, WO-CLOSED-OVER
        assert body["closed_count"] == 2
        # H: WO-HOLD-OLD
        assert body["hold_count"] == 1
        # Overdue (open/hold past 30d): WO-OPEN-OLD + WO-HOLD-OLD
        assert body["overdue_count"] == 2
        assert body["overdue_threshold_days"] == 30

        # avg age of open (not hold): (10 + 45) / 2 = 27.5
        assert body["avg_age_days_open"] == pytest.approx(27.5)

        # Total cost = 150 + 7000 + 750 + 400 + 15000 = 23300
        assert body["total_cost_to_date"] == pytest.approx(23300.0)
        # Total budget = 300 + 5000 + 1500 + 500 + 10000 = 17300
        assert body["total_budget"] == pytest.approx(17300.0)

    def test_overdue_days_override(self, client: TestClient):
        # Bump threshold well past WO-OPEN-OLD's 45d / WO-HOLD-OLD's 50d.
        resp = client.get("/api/work-orders/summary?overdue_days=60")
        body = resp.json()
        assert body["overdue_threshold_days"] == 60
        assert body["overdue_count"] == 0


# --------------------------------------------------------------------------- #
# /list                                                                       #
# --------------------------------------------------------------------------- #


class TestList:
    def test_pagination_and_total(self, client: TestClient):
        resp = client.get("/api/work-orders/list?page=1&page_size=2")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 6
        assert body["page"] == 1
        assert body["page_size"] == 2
        assert len(body["items"]) == 2

        resp2 = client.get("/api/work-orders/list?page=3&page_size=2")
        assert resp2.json()["page"] == 3
        assert len(resp2.json()["items"]) == 2

    def test_filter_by_status_open(self, client: TestClient):
        resp = client.get("/api/work-orders/list?status=open")
        items = resp.json()["items"]
        assert {i["work_order"] for i in items} == {"WO-OPEN-FRESH", "WO-OPEN-OLD"}
        assert all(i["status"] == "open" for i in items)

    def test_filter_by_priority_critical(self, client: TestClient):
        resp = client.get("/api/work-orders/list?priority=critical")
        items = resp.json()["items"]
        # WO-OPEN-OLD and WO-CLOSED-OVER are priority=1 (critical).
        assert {i["work_order"] for i in items} == {"WO-OPEN-OLD", "WO-CLOSED-OVER"}

    def test_filter_overdue_true(self, client: TestClient):
        resp = client.get("/api/work-orders/list?overdue=true")
        items = resp.json()["items"]
        assert {i["work_order"] for i in items} == {"WO-OPEN-OLD", "WO-HOLD-OLD"}
        assert all(i["overdue"] is True for i in items)

    def test_filter_overdue_false(self, client: TestClient):
        resp = client.get("/api/work-orders/list?overdue=false")
        items = resp.json()["items"]
        # Everyone except the two overdue ones.
        assert "WO-OPEN-OLD" not in {i["work_order"] for i in items}
        assert "WO-HOLD-OLD" not in {i["work_order"] for i in items}
        assert len(items) == 4

    def test_filter_by_equipment_exact(self, client: TestClient):
        resp = client.get("/api/work-orders/list?equipment=TRUCK-02")
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["work_order"] == "WO-OPEN-OLD"

    def test_filter_by_mechanic_case_insensitive(self, client: TestClient):
        resp = client.get("/api/work-orders/list?mechanic=carol")
        items = resp.json()["items"]
        assert {i["work_order"] for i in items} == {
            "WO-OPEN-OLD", "WO-HOLD-OLD", "WO-CLOSED-OVER",
        }

    def test_search_substring(self, client: TestClient):
        resp = client.get("/api/work-orders/list?search=transmission")
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["work_order"] == "WO-OPEN-OLD"

    def test_search_matches_job_number(self, client: TestClient):
        resp = client.get("/api/work-orders/list?search=JOB-104")
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["work_order"] == "WO-CLOSED-OVER"

    def test_sort_by_total_cost_desc(self, client: TestClient):
        resp = client.get(
            "/api/work-orders/list?sort_by=total_cost&sort_dir=desc"
        )
        items = resp.json()["items"]
        # WO-CLOSED-OVER (15000) > WO-OPEN-OLD (7000) > ...
        assert items[0]["work_order"] == "WO-CLOSED-OVER"
        assert items[1]["work_order"] == "WO-OPEN-OLD"

    def test_sort_by_age_days_desc(self, client: TestClient):
        resp = client.get(
            "/api/work-orders/list?sort_by=age_days&sort_dir=desc"
        )
        items = resp.json()["items"]
        # Ages: CLOSED-OVER (lifespan 40), CLOSED-OK (20), HOLD-OLD (50 open),
        #       OPEN-OLD (45 open), OPEN-FRESH (10), UNKNOWN (5 open).
        # So sorted desc: HOLD-OLD (50) > OPEN-OLD (45) > CLOSED-OVER (40) > ...
        assert items[0]["work_order"] == "WO-HOLD-OLD"
        assert items[0]["age_days"] == 50


# --------------------------------------------------------------------------- #
# /{work_order}                                                               #
# --------------------------------------------------------------------------- #


class TestDetail:
    def test_open_overdue_detail(self, client: TestClient):
        resp = client.get("/api/work-orders/WO-OPEN-OLD")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["id"] == "WO-OPEN-OLD"
        assert body["status"] == "open"
        assert body["priority"] == "critical"
        assert body["overdue"] is True
        assert body["age_days"] == 45
        # variance = 7000 - 5000 = 2000; pct = 40%
        assert body["cost_variance"] == pytest.approx(2000.0)
        assert body["cost_variance_pct"] == pytest.approx(40.0)

    def test_closed_detail_uses_lifespan_age(self, client: TestClient):
        resp = client.get("/api/work-orders/WO-CLOSED-OK")
        body = resp.json()
        assert body["status"] == "closed"
        # lifespan = closed_date - open_date = 30 - 10 = 20 days
        assert body["age_days"] == 20
        assert body["overdue"] is False
        assert body["cost_variance"] == pytest.approx(-100.0)

    def test_unknown_status_and_priority_normalize(self, client: TestClient):
        resp = client.get("/api/work-orders/WO-UNKNOWN")
        body = resp.json()
        assert body["status"] == "unknown"
        assert body["priority"] == "unknown"
        # Missing budget/total -> variance is None.
        assert body["cost_variance"] is None
        assert body["cost_variance_pct"] is None

    def test_detail_404_on_missing(self, client: TestClient):
        resp = client.get("/api/work-orders/GHOST-WO-99")
        assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# /insights                                                                   #
# --------------------------------------------------------------------------- #


class TestInsights:
    def test_status_counts(self, client: TestClient):
        resp = client.get("/api/work-orders/insights")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        sc = body["status_counts"]
        assert sc == {"open": 2, "closed": 2, "hold": 1, "unknown": 1}

    def test_avg_age_open(self, client: TestClient):
        resp = client.get("/api/work-orders/insights")
        body = resp.json()
        # Open ages: 10, 45 -> avg 27.5
        assert body["avg_age_days_open"] == pytest.approx(27.5)

    def test_overdue_count(self, client: TestClient):
        resp = client.get("/api/work-orders/insights")
        body = resp.json()
        assert body["overdue_count"] == 2
        assert body["overdue_threshold_days"] == 30

    def test_cost_vs_budget(self, client: TestClient):
        resp = client.get("/api/work-orders/insights")
        body = resp.json()
        cvb = body["cost_vs_budget"]
        # cost_to_date = 23300, budget = 17300, variance = 6000
        assert cvb["cost_to_date"] == pytest.approx(23300.0)
        assert cvb["budget"] == pytest.approx(17300.0)
        assert cvb["variance"] == pytest.approx(6000.0)
        # variance_pct = 6000 / 17300 * 100 ≈ 34.68%
        assert cvb["variance_pct"] == pytest.approx(6000.0 / 17300.0 * 100.0)

    def test_insights_overdue_override(self, client: TestClient):
        resp = client.get("/api/work-orders/insights?overdue_days=60")
        body = resp.json()
        assert body["overdue_threshold_days"] == 60
        assert body["overdue_count"] == 0
