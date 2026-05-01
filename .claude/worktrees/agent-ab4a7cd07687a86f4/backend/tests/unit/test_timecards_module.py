"""Tests for app.modules.timecards.

Strategy mirrors the equipment and work_orders tests:
  1. Fresh SQLite DB per test via fixtures.
  2. Register every mart Table against Base.metadata, create_all().
  3. Seed four canonical classes (over, under, on_track, orphan-projected)
     with known avg_12mo_a values, plus one with overtime and one without.
  4. Seed an overhead-actual row + job_type-actual row so the summary
     can compute overhead_ratio and total_job_types correctly.
  5. Drive the API through TestClient with dependency overrides.

The class seeds are chosen so variance_pct math is integer-clean:
  CLASS-OVER:    actual=12,  projected=10  -> variance=+2,  pct=+20%   (OVER)
  CLASS-UNDER:   actual=8,   projected=10  -> variance=-2,  pct=-20%   (UNDER)
  CLASS-TRACK:   actual=10,  projected=10  -> variance=0,   pct=0%     (ON_TRACK)
  CLASS-ORPHAN:  actual=None, projected=5  -> variance=None             (UNKNOWN)

Overtime seeds:
  CLASS-OVER:    monthly_hours=160, last_month_actuals=200 -> OT=40, 25%
  CLASS-UNDER:   monthly_hours=160, last_month_actuals=150 -> OT=0,  0%
  CLASS-TRACK:   monthly_hours=160, last_month_actuals=160 -> OT=0,  0%
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import sessionmaker

# Register every mart Table against Base.metadata.
import app.services.excel_marts  # noqa: F401
from app.core.database import Base
from app.models.tenant import SubscriptionTier, Tenant, TenantStatus
from app.modules.timecards.router import (
    _default_engine,
    get_engine,
    get_tenant_id,
    router as timecards_router,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


NOW = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _insert_class_actual(conn, tenant_id: str, row: dict) -> None:
    """Helper — inserts into mart_fte_class_actual (19 cols + tenant_id)."""
    # Build the INSERT dynamically so we only touch columns we care about;
    # the rest default to NULL, which is fine for tests.
    cols = ",".join(row.keys())
    placeholders = ",".join(f":{k}" for k in row.keys())
    conn.execute(
        text(
            f"INSERT INTO mart_fte_class_actual (tenant_id, {cols}) "
            f"VALUES (:tenant_id, {placeholders})"
        ),
        {"tenant_id": tenant_id, **row},
    )


def _insert_class_projected(conn, tenant_id: str, row: dict) -> None:
    cols = ",".join(row.keys())
    placeholders = ",".join(f":{k}" for k in row.keys())
    conn.execute(
        text(
            f"INSERT INTO mart_fte_class_projected (tenant_id, {cols}) "
            f"VALUES (:tenant_id, {placeholders})"
        ),
        {"tenant_id": tenant_id, **row},
    )


@pytest.fixture
def seeded_engine(tmp_path) -> Engine:
    url = f"sqlite:///{tmp_path / 'timecards_test.db'}"
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
        # --- class actuals ---
        _insert_class_actual(conn, tenant_id, {
            "class_name": "CLASS-OVER",
            "code": "OV-01",
            "craft_class": "Operator",
            "monthly_hours": 160.0,
            "last_month_actuals": 200.0,   # 40h overtime
            "avg_12mo_a": 12.0,
            "feb_24": 11.0, "mar_24": 12.0, "jan_25": 13.0,
            "avg_12mo_b": 12.0,
        })
        _insert_class_actual(conn, tenant_id, {
            "class_name": "CLASS-UNDER",
            "code": "UN-01",
            "craft_class": "Laborer",
            "monthly_hours": 160.0,
            "last_month_actuals": 150.0,   # no overtime
            "avg_12mo_a": 8.0,
            "feb_24": 8.0, "mar_24": 8.0, "jan_25": 8.0,
            "avg_12mo_b": 8.0,
        })
        _insert_class_actual(conn, tenant_id, {
            "class_name": "CLASS-TRACK",
            "code": "TR-01",
            "craft_class": "Carpenter",
            "monthly_hours": 160.0,
            "last_month_actuals": 160.0,   # exactly on budget
            "avg_12mo_a": 10.0,
            "feb_24": 10.0, "mar_24": 10.0, "jan_25": 10.0,
            "avg_12mo_b": 10.0,
        })

        # --- class projected (matches first three, plus ORPHAN) ---
        _insert_class_projected(conn, tenant_id, {
            "class_name": "CLASS-OVER",
            "code": "OV-01",
            "craft_class": "Operator",
            "monthly_hours": 160.0,
            "last_month_actuals": 0.0,
            "avg_12mo_a": 10.0,
            "apr_26": 10.0, "mar_29": 10.0,
            "avg_12mo_b": 10.0,
            "avg_24mo": 10.0,
            "avg_36mo": 10.0,
        })
        _insert_class_projected(conn, tenant_id, {
            "class_name": "CLASS-UNDER",
            "code": "UN-01",
            "craft_class": "Laborer",
            "monthly_hours": 160.0,
            "last_month_actuals": 0.0,
            "avg_12mo_a": 10.0,
            "apr_26": 10.0, "mar_29": 10.0,
            "avg_12mo_b": 10.0,
            "avg_24mo": 10.0,
            "avg_36mo": 10.0,
        })
        _insert_class_projected(conn, tenant_id, {
            "class_name": "CLASS-TRACK",
            "code": "TR-01",
            "craft_class": "Carpenter",
            "monthly_hours": 160.0,
            "last_month_actuals": 0.0,
            "avg_12mo_a": 10.0,
            "apr_26": 10.0, "mar_29": 10.0,
            "avg_12mo_b": 10.0,
            "avg_24mo": 10.0,
            "avg_36mo": 10.0,
        })
        _insert_class_projected(conn, tenant_id, {
            "class_name": "CLASS-ORPHAN",
            "code": "OR-01",
            "craft_class": "Ironworker",
            "monthly_hours": 160.0,
            "last_month_actuals": 0.0,
            "avg_12mo_a": 5.0,
            "apr_26": 5.0, "mar_29": 5.0,
            "avg_12mo_b": 5.0,
            "avg_24mo": 5.0,
            "avg_36mo": 5.0,
        })

        # --- overhead actual: 6 FTE across 2 departments ---
        conn.execute(
            text(
                """
                INSERT INTO mart_fte_overhead_actual
                    (tenant_id, department, monthly_hours, last_month_actuals,
                     avg_12mo_a)
                VALUES (:tenant_id, :department, :monthly_hours,
                        :last_month_actuals, :avg_12mo_a)
                """
            ),
            {
                "tenant_id": tenant_id,
                "department": "Accounting",
                "monthly_hours": 160.0,
                "last_month_actuals": 160.0,
                "avg_12mo_a": 4.0,
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO mart_fte_overhead_actual
                    (tenant_id, department, monthly_hours, last_month_actuals,
                     avg_12mo_a)
                VALUES (:tenant_id, :department, :monthly_hours,
                        :last_month_actuals, :avg_12mo_a)
                """
            ),
            {
                "tenant_id": tenant_id,
                "department": "IT",
                "monthly_hours": 160.0,
                "last_month_actuals": 160.0,
                "avg_12mo_a": 2.0,
            },
        )

        # --- job_type actuals (for total_job_types count only) ---
        for jt in ("Field", "Office"):
            conn.execute(
                text(
                    """
                    INSERT INTO mart_fte_type_actual
                        (tenant_id, job_type, monthly_hours,
                         last_month_actuals, avg_12mo_a)
                    VALUES (:tenant_id, :job_type, 160.0, 160.0, 5.0)
                    """
                ),
                {"tenant_id": tenant_id, "job_type": jt},
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
    app.include_router(timecards_router, prefix="/api/timecards")

    app.dependency_overrides[get_engine] = lambda: seeded_engine
    app.dependency_overrides[get_tenant_id] = lambda: seeded_tenant_id

    _default_engine.cache_clear()

    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# /summary                                                                    #
# --------------------------------------------------------------------------- #


class TestSummary:
    def test_kpi_tiles(self, client: TestClient):
        resp = client.get("/api/timecards/summary")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["total_classes"] == 3
        assert body["total_overhead_departments"] == 2
        assert body["total_job_types"] == 2

        # actuals: CLASS-OVER(12) + CLASS-UNDER(8) + CLASS-TRACK(10) = 30
        # CLASS-ORPHAN has no actual, so it contributes 0.
        assert body["total_actual_fte"] == pytest.approx(30.0)

        # projected: 10+10+10+5 = 35
        assert body["total_projected_fte"] == pytest.approx(35.0)

        # total_variance_pct = (30-35)/35 * 100 = -14.285...
        assert body["total_variance_pct"] == pytest.approx(
            (30.0 - 35.0) / 35.0 * 100.0
        )

        # Overtime: CLASS-OVER is the only one above budget (40h / 160h = 25%)
        assert body["classes_with_overtime"] == 1
        # avg_overtime_pct: mean of (25.0, 0.0, 0.0) = 8.333...
        assert body["avg_overtime_pct"] == pytest.approx(25.0 / 3.0)

        # Overhead ratio: overhead=6, direct=30 -> 6/36 = 16.666...%
        assert body["overhead_ratio_pct"] == pytest.approx(6.0 / 36.0 * 100.0)

    def test_band_pct_widens_on_track_region(self, client: TestClient):
        # With band=25%, CLASS-OVER (+20%) and CLASS-UNDER (-20%) both
        # fall inside on_track. Summary itself doesn't filter by status,
        # but the knob passes through — verify it doesn't break the call.
        resp = client.get("/api/timecards/summary?band_pct=25")
        assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# /list                                                                       #
# --------------------------------------------------------------------------- #


class TestList:
    def test_pagination_and_total(self, client: TestClient):
        resp = client.get("/api/timecards/list?page=1&page_size=2")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 4
        assert body["page"] == 1
        assert body["page_size"] == 2
        assert len(body["items"]) == 2

        resp2 = client.get("/api/timecards/list?page=2&page_size=2")
        assert resp2.json()["page"] == 2
        assert len(resp2.json()["items"]) == 2

    def test_filter_by_status_over(self, client: TestClient):
        resp = client.get("/api/timecards/list?status=over")
        items = resp.json()["items"]
        assert {i["class_name"] for i in items} == {"CLASS-OVER"}
        assert items[0]["variance_status"] == "over"
        assert items[0]["variance_pct"] == pytest.approx(20.0)

    def test_filter_by_status_under(self, client: TestClient):
        resp = client.get("/api/timecards/list?status=under")
        items = resp.json()["items"]
        assert {i["class_name"] for i in items} == {"CLASS-UNDER"}
        assert items[0]["variance_pct"] == pytest.approx(-20.0)

    def test_filter_by_status_on_track(self, client: TestClient):
        resp = client.get("/api/timecards/list?status=on_track")
        items = resp.json()["items"]
        assert {i["class_name"] for i in items} == {"CLASS-TRACK"}

    def test_filter_by_status_unknown(self, client: TestClient):
        # CLASS-ORPHAN has no actual -> variance_status=unknown
        resp = client.get("/api/timecards/list?status=unknown")
        items = resp.json()["items"]
        assert {i["class_name"] for i in items} == {"CLASS-ORPHAN"}

    def test_filter_overtime_only_true(self, client: TestClient):
        resp = client.get("/api/timecards/list?overtime_only=true")
        items = resp.json()["items"]
        assert {i["class_name"] for i in items} == {"CLASS-OVER"}
        assert items[0]["overtime_hours"] == pytest.approx(40.0)
        assert items[0]["overtime_pct"] == pytest.approx(25.0)

    def test_filter_overtime_only_false(self, client: TestClient):
        resp = client.get("/api/timecards/list?overtime_only=false")
        items = resp.json()["items"]
        names = {i["class_name"] for i in items}
        assert "CLASS-OVER" not in names
        # CLASS-TRACK, CLASS-UNDER, CLASS-ORPHAN (orphan has 0 overtime).
        assert names == {"CLASS-UNDER", "CLASS-TRACK", "CLASS-ORPHAN"}

    def test_search_by_craft_class(self, client: TestClient):
        resp = client.get("/api/timecards/list?search=operator")
        items = resp.json()["items"]
        assert {i["class_name"] for i in items} == {"CLASS-OVER"}

    def test_sort_by_variance_pct_desc(self, client: TestClient):
        resp = client.get(
            "/api/timecards/list?sort_by=variance_pct&sort_dir=desc"
        )
        items = resp.json()["items"]
        # OVER (+20) > TRACK (0) > UNDER (-20) > ORPHAN (None)
        assert items[0]["class_name"] == "CLASS-OVER"
        assert items[1]["class_name"] == "CLASS-TRACK"
        assert items[2]["class_name"] == "CLASS-UNDER"
        assert items[3]["class_name"] == "CLASS-ORPHAN"  # None last

    def test_sort_by_actual_avg_fte_asc(self, client: TestClient):
        resp = client.get(
            "/api/timecards/list?sort_by=actual_avg_fte&sort_dir=asc"
        )
        items = resp.json()["items"]
        # UNDER(8) < TRACK(10) < OVER(12), ORPHAN (None) last
        assert items[0]["class_name"] == "CLASS-UNDER"
        assert items[-1]["class_name"] == "CLASS-ORPHAN"


# --------------------------------------------------------------------------- #
# /{class_name}                                                               #
# --------------------------------------------------------------------------- #


class TestDetail:
    def test_detail_over_has_monthly_breakdown(self, client: TestClient):
        resp = client.get("/api/timecards/CLASS-OVER")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["class_name"] == "CLASS-OVER"
        assert body["variance_status"] == "over"
        assert body["variance"] == pytest.approx(2.0)
        assert body["variance_pct"] == pytest.approx(20.0)
        assert body["overtime_pct"] == pytest.approx(25.0)

        # We seeded feb_24/mar_24/jan_25 on actual, apr_26/mar_29 on
        # projected; breakdown should contain all non-null months.
        months = {m["month"] for m in body["monthly_breakdown"]}
        assert {"Feb 24", "Mar 24", "Jan 25", "Apr 26", "Mar 29"} <= months

        # Feb 24 row has actual only (projected is None).
        feb = next(m for m in body["monthly_breakdown"] if m["month"] == "Feb 24")
        assert feb["actual"] == pytest.approx(11.0)
        assert feb["projected"] is None

        apr = next(m for m in body["monthly_breakdown"] if m["month"] == "Apr 26")
        assert apr["actual"] is None
        assert apr["projected"] == pytest.approx(10.0)

    def test_detail_orphan_has_only_projected(self, client: TestClient):
        resp = client.get("/api/timecards/CLASS-ORPHAN")
        assert resp.status_code == 200
        body = resp.json()
        assert body["actual_avg_fte"] is None
        assert body["projected_avg_fte"] == pytest.approx(5.0)
        assert body["variance_status"] == "unknown"
        # Only projected-window months survive.
        assert all(m["actual"] is None for m in body["monthly_breakdown"])

    def test_detail_404_on_unknown(self, client: TestClient):
        resp = client.get("/api/timecards/GHOST-CLASS")
        assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# /insights                                                                   #
# --------------------------------------------------------------------------- #


class TestInsights:
    def test_variance_over_and_under(self, client: TestClient):
        resp = client.get("/api/timecards/insights")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["variance_band_pct"] == pytest.approx(10.0)

        over = body["variance_over"]
        assert [v["class_name"] for v in over] == ["CLASS-OVER"]
        assert over[0]["variance_pct"] == pytest.approx(20.0)

        under = body["variance_under"]
        assert [v["class_name"] for v in under] == ["CLASS-UNDER"]
        assert under[0]["variance_pct"] == pytest.approx(-20.0)

    def test_overtime_leaders(self, client: TestClient):
        resp = client.get("/api/timecards/insights")
        body = resp.json()
        ot = body["overtime_leaders"]
        assert [o["class_name"] for o in ot] == ["CLASS-OVER"]
        assert ot[0]["overtime_hours"] == pytest.approx(40.0)
        assert ot[0]["overtime_pct"] == pytest.approx(25.0)

    def test_overhead_ratio(self, client: TestClient):
        resp = client.get("/api/timecards/insights")
        body = resp.json()["overhead_ratio"]
        assert body["overhead_fte"] == pytest.approx(6.0)
        assert body["direct_fte"] == pytest.approx(30.0)
        assert body["ratio_pct"] == pytest.approx(6.0 / 36.0 * 100.0)

    def test_top_n_caps_lists(self, client: TestClient):
        resp = client.get("/api/timecards/insights?top_n=1")
        body = resp.json()
        assert len(body["variance_over"]) <= 1
        assert len(body["variance_under"]) <= 1
        assert len(body["overtime_leaders"]) <= 1

    def test_band_pct_collapses_over_into_on_track(self, client: TestClient):
        # With band=25%, CLASS-OVER (+20%) falls inside on_track and
        # drops off the variance_over list.
        resp = client.get("/api/timecards/insights?band_pct=25")
        body = resp.json()
        # variance_over filters by variance_pct > 0, not by status —
        # so CLASS-OVER still appears here. But its status should now be
        # on_track. Pick it out of the flat list and verify.
        over = body["variance_over"]
        assert any(
            v["class_name"] == "CLASS-OVER"
            and v["variance_status"] == "on_track"
            for v in over
        )
