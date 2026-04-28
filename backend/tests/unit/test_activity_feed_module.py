"""Tests for app.modules.activity_feed.

Strategy mirrors the per-module suites:
  1. Build a fresh SQLite DB per test via fixtures.
  2. ``Base.metadata.create_all`` builds the schema for ``tenants``,
     ``ingest_log``, ``usage_events``, and ``llm_insights`` (all four
     models are imported by ``tests/conftest.py``).
  3. Seed each of the three event sources with rows that exercise
     every (kind, severity) pair, plus one out-of-window row per
     source so lookback filtering is observable.
  4. Drive the API through ``TestClient`` with dependency overrides.

Severity rules under test:

  * ``ingest_log.status="error"``   -> critical / kind=ingest_failed
  * ``ingest_log.status="partial"`` -> warning  / kind=ingest_partial
  * ``ingest_log.status="ok"``      -> info     / kind=ingest_ok
  * ``usage_events`` with cost >= AGENT_CALL_COST_THRESHOLD -> warning
  * ``usage_events`` everything else  -> info
  * ``llm_insights`` always           -> info
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.ingest_log import IngestLog
from app.models.llm_insight import LlmInsight
from app.models.tenant import SubscriptionTier, Tenant, TenantStatus
from app.models.usage import UsageEvent
from app.modules.activity_feed.router import (
    _default_engine,
    get_engine,
    get_tenant_id,
    router as activity_router,
)
from app.modules.activity_feed.schema import (
    ActivityKind,
    ActivitySeverity,
)
from app.modules.activity_feed.service import (
    AGENT_CALL_COST_THRESHOLD,
    DEFAULT_LOOKBACK_DAYS,
    get_feed,
    get_summary,
)


# Pinned at import time so the seed stays deterministic within a run.
NOW = datetime.now(timezone.utc).replace(microsecond=0)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def seeded_engine(tmp_path) -> Engine:
    """SQLite file with schema + a representative cross-source seed."""
    url = f"sqlite:///{tmp_path / 'activity_feed_test.db'}"
    engine = create_engine(url, future=True)
    Base.metadata.create_all(engine)

    tenant_id = str(uuid.uuid4())
    other_tenant_id = str(uuid.uuid4())

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
        # Second tenant — no rows under it should ever leak into the
        # vancon feed, which is what tenant scoping must guarantee.
        s.add(
            Tenant(
                id=other_tenant_id,
                slug="other-co",
                company_name="OtherCo",
                contact_email="admin@other.test",
                tier=SubscriptionTier.STARTER,
                status=TenantStatus.ACTIVE,
            )
        )
        s.commit()

        # ---- ingest_log -------------------------------------------------
        # Three in-window rows (one per status) + one ancient row that
        # falls outside DEFAULT_LOOKBACK_DAYS.
        s.add_all([
            IngestLog(
                tenant_id=tenant_id,
                job_name="productivity.labor",
                source_file="/data/labor.xlsx",
                target_table="mart_productivity_labor",
                status="ok",
                rows_read=2008,
                rows_written=2008,
                rows_skipped=0,
                duration_ms=1234,
                started_at=NOW - timedelta(hours=2),
                finished_at=NOW - timedelta(hours=2, minutes=-2),
            ),
            IngestLog(
                tenant_id=tenant_id,
                job_name="vendors",
                source_file="/data/vendors.xlsx",
                target_table="mart_vendors",
                status="partial",
                rows_read=200,
                rows_written=180,
                rows_skipped=20,
                duration_ms=999,
                started_at=NOW - timedelta(days=2),
                finished_at=NOW - timedelta(days=2, hours=-1),
            ),
            IngestLog(
                tenant_id=tenant_id,
                job_name="bids.outlook",
                source_file="/data/bids.xlsx",
                target_table="mart_bids_outlook",
                status="error",
                rows_read=0,
                rows_written=0,
                rows_skipped=0,
                errors='["sheet not found", "missing column owner"]',
                duration_ms=12,
                started_at=NOW - timedelta(days=5),
                finished_at=None,
            ),
            IngestLog(
                tenant_id=tenant_id,
                job_name="ancient.run",
                source_file="/data/ancient.xlsx",
                target_table="mart_ancient",
                status="ok",
                rows_read=10,
                rows_written=10,
                rows_skipped=0,
                duration_ms=50,
                started_at=NOW - timedelta(days=DEFAULT_LOOKBACK_DAYS + 5),
                finished_at=NOW - timedelta(days=DEFAULT_LOOKBACK_DAYS + 5),
            ),
            # Tenant-isolation guard.
            IngestLog(
                tenant_id=other_tenant_id,
                job_name="leakage.canary",
                source_file="/data/leak.xlsx",
                target_table="mart_leak",
                status="error",
                rows_read=0,
                rows_written=0,
                rows_skipped=0,
                duration_ms=1,
                started_at=NOW - timedelta(hours=1),
                finished_at=None,
            ),
        ])

        # ---- usage_events ----------------------------------------------
        # 3 cheap (info) calls + 1 expensive call (warning) + 1 ancient
        # cheap call out of window. The expensive cost is set to exceed
        # AGENT_CALL_COST_THRESHOLD by design.
        s.add_all([
            UsageEvent(
                tenant_id=tenant_id,
                agent="job_cost_coding",
                model="claude-sonnet-4-20250514",
                input_tokens=1243,
                output_tokens=412,
                cost_usd=0.012,
                job_number="J-1001",
                created_at=NOW - timedelta(minutes=30),
            ),
            UsageEvent(
                tenant_id=tenant_id,
                agent="bid_agent",
                model="claude-sonnet-4-20250514",
                input_tokens=900,
                output_tokens=300,
                cost_usd=0.009,
                created_at=NOW - timedelta(hours=4),
            ),
            UsageEvent(
                tenant_id=tenant_id,
                agent="media_agent",
                model="claude-sonnet-4-20250514",
                input_tokens=500,
                output_tokens=200,
                cost_usd=0.005,
                created_at=NOW - timedelta(days=3),
            ),
            UsageEvent(
                tenant_id=tenant_id,
                agent="proposal_agent",
                model="claude-opus-4-20250514",
                input_tokens=15_000,
                output_tokens=4_000,
                cost_usd=AGENT_CALL_COST_THRESHOLD + 0.25,
                created_at=NOW - timedelta(hours=10),
            ),
            UsageEvent(
                tenant_id=tenant_id,
                agent="job_cost_coding",
                model="claude-sonnet-4-20250514",
                input_tokens=100,
                output_tokens=50,
                cost_usd=0.001,
                created_at=NOW - timedelta(days=DEFAULT_LOOKBACK_DAYS + 10),
            ),
            # Tenant-isolation guard.
            UsageEvent(
                tenant_id=other_tenant_id,
                agent="canary_agent",
                model="claude-sonnet-4-20250514",
                input_tokens=1,
                output_tokens=1,
                cost_usd=99.0,
                created_at=NOW - timedelta(minutes=1),
            ),
        ])

        # ---- llm_insights ----------------------------------------------
        s.add_all([
            LlmInsight(
                tenant_id=tenant_id,
                module="executive_dashboard",
                revision_token="abc123",
                payload_json='{"recommendations": []}',
                input_tokens=10_000,
                output_tokens=2_000,
                model="claude-opus-4-20250514",
                created_at=NOW - timedelta(hours=1),
            ),
            LlmInsight(
                tenant_id=tenant_id,
                module="vendors",
                revision_token="def456",
                payload_json='{"recommendations": []}',
                input_tokens=5_000,
                output_tokens=1_000,
                model="claude-opus-4-20250514",
                created_at=NOW - timedelta(days=1),
            ),
            # Out of window.
            LlmInsight(
                tenant_id=tenant_id,
                module="ancient",
                revision_token="ghi789",
                payload_json='{}',
                input_tokens=1,
                output_tokens=1,
                model="claude-opus-4-20250514",
                created_at=NOW - timedelta(days=DEFAULT_LOOKBACK_DAYS + 20),
            ),
        ])

        s.commit()

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
    app.include_router(activity_router, prefix="/api/activity-feed")
    app.dependency_overrides[get_engine] = lambda: seeded_engine
    app.dependency_overrides[get_tenant_id] = lambda: seeded_tenant_id
    _default_engine.cache_clear()
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# Service-level tests                                                         #
# --------------------------------------------------------------------------- #


class TestGetFeed:
    """The merged + sorted timeline."""

    def test_in_window_event_count(self, seeded_engine, seeded_tenant_id):
        feed = get_feed(seeded_engine, seeded_tenant_id)
        # 3 ingest + 4 usage + 2 insight = 9 in window.
        assert feed.total_matching == 9
        assert feed.total_returned == 9
        assert len(feed.items) == 9

    def test_out_of_window_excluded(self, seeded_engine, seeded_tenant_id):
        feed = get_feed(seeded_engine, seeded_tenant_id)
        # The "ancient" rows are far past DEFAULT_LOOKBACK_DAYS.
        assert all("ancient" not in (e.entity_ref or "").lower()
                   for e in feed.items)
        assert all(e.detail.get("module") != "ancient" for e in feed.items)

    def test_severity_classification(self, seeded_engine, seeded_tenant_id):
        feed = get_feed(seeded_engine, seeded_tenant_id)
        sev_count = {s: 0 for s in ActivitySeverity}
        for e in feed.items:
            sev_count[e.severity] += 1
        # 1 critical (ingest_failed), 2 warnings (ingest_partial + costly
        # agent_call), 6 info (1 ingest_ok + 3 cheap agent_calls + 2 insights).
        assert sev_count[ActivitySeverity.CRITICAL] == 1
        assert sev_count[ActivitySeverity.WARNING] == 2
        assert sev_count[ActivitySeverity.INFO] == 6

    def test_kind_classification(self, seeded_engine, seeded_tenant_id):
        feed = get_feed(seeded_engine, seeded_tenant_id)
        kind_count = {k: 0 for k in ActivityKind}
        for e in feed.items:
            kind_count[e.kind] += 1
        assert kind_count[ActivityKind.INGEST_OK] == 1
        assert kind_count[ActivityKind.INGEST_PARTIAL] == 1
        assert kind_count[ActivityKind.INGEST_FAILED] == 1
        assert kind_count[ActivityKind.AGENT_CALL] == 4
        assert kind_count[ActivityKind.INSIGHT_GENERATED] == 2

    def test_sort_severity_then_recency(self, seeded_engine, seeded_tenant_id):
        feed = get_feed(seeded_engine, seeded_tenant_id)
        # Severity descending: critical(3) > warning(2) > info(1).
        ranks = {
            ActivitySeverity.CRITICAL: 3,
            ActivitySeverity.WARNING: 2,
            ActivitySeverity.INFO: 1,
        }
        sev_ranks = [ranks[e.severity] for e in feed.items]
        assert sev_ranks == sorted(sev_ranks, reverse=True)

        # Within the same severity tier, occurred_at must descend.
        from itertools import groupby
        for _, grp in groupby(feed.items, key=lambda e: e.severity):
            times = [e.occurred_at for e in grp]
            assert times == sorted(times, reverse=True)

    def test_top_n_caps_results(self, seeded_engine, seeded_tenant_id):
        feed = get_feed(seeded_engine, seeded_tenant_id, top_n=3)
        assert feed.total_returned == 3
        assert feed.total_matching == 9
        # The capped slice is the loudest 3.
        assert feed.items[0].severity == ActivitySeverity.CRITICAL

    def test_filter_by_kind(self, seeded_engine, seeded_tenant_id):
        feed = get_feed(
            seeded_engine, seeded_tenant_id, kind=ActivityKind.AGENT_CALL,
        )
        assert all(e.kind is ActivityKind.AGENT_CALL for e in feed.items)
        assert feed.total_matching == 4

    def test_filter_by_severity(self, seeded_engine, seeded_tenant_id):
        feed = get_feed(
            seeded_engine, seeded_tenant_id, severity=ActivitySeverity.CRITICAL,
        )
        assert feed.total_matching == 1
        assert feed.items[0].kind is ActivityKind.INGEST_FAILED

    def test_explicit_since_overrides_lookback(
        self, seeded_engine, seeded_tenant_id,
    ):
        # since = 6 hours ago -> only events newer than that count.
        # That's: ingest 'ok' (2h ago), usage J-1001 (30min), bid_agent
        # (4h ago), insight EXEC (1h ago). 4 total.
        since = NOW - timedelta(hours=6)
        feed = get_feed(seeded_engine, seeded_tenant_id, since=since)
        assert feed.total_matching == 4

    def test_id_format(self, seeded_engine, seeded_tenant_id):
        feed = get_feed(seeded_engine, seeded_tenant_id)
        prefixes = {e.id.split(":")[0] for e in feed.items}
        assert prefixes == {"ingest", "usage", "insight"}

    def test_tenant_isolation(self, seeded_engine, seeded_tenant_id):
        feed = get_feed(seeded_engine, seeded_tenant_id)
        # OtherCo seeded a critical ingest + a $99 agent call. Neither
        # may show up under vancon.
        assert all("leak" not in (e.entity_ref or "").lower()
                   for e in feed.items)
        assert all(e.actor != "canary_agent" for e in feed.items)
        assert all(float(e.detail.get("cost_usd", 0)) < 99.0
                   for e in feed.items if e.kind is ActivityKind.AGENT_CALL)


class TestGetSummary:
    """The tile-strip rollup."""

    def test_total_matches_window(self, seeded_engine, seeded_tenant_id):
        s = get_summary(seeded_engine, seeded_tenant_id)
        assert s.total == 9

    def test_severity_rollup(self, seeded_engine, seeded_tenant_id):
        s = get_summary(seeded_engine, seeded_tenant_id)
        assert s.by_severity.critical == 1
        assert s.by_severity.warning == 2
        assert s.by_severity.info == 6

    def test_kind_rollup(self, seeded_engine, seeded_tenant_id):
        s = get_summary(seeded_engine, seeded_tenant_id)
        assert s.by_kind.ingest_ok == 1
        assert s.by_kind.ingest_partial == 1
        assert s.by_kind.ingest_failed == 1
        assert s.by_kind.agent_call == 4
        assert s.by_kind.insight_generated == 2

    def test_last_24h_window(self, seeded_engine, seeded_tenant_id):
        s = get_summary(seeded_engine, seeded_tenant_id)
        # In <24h: ingest_ok (2h), usage J-1001 (30m), usage bid_agent
        # (4h), usage proposal_agent (10h), insight executive_dashboard (1h).
        # = 5 events.
        assert s.last_24h == 5

    def test_last_7d_window(self, seeded_engine, seeded_tenant_id):
        s = get_summary(seeded_engine, seeded_tenant_id)
        # In <=7d: 3 ingest (2h, 2d, 5d) + 4 usage (30m, 4h, 3d, 10h)
        # + 2 insights (1h, 1d) = 9.
        assert s.last_7d == 9


# --------------------------------------------------------------------------- #
# HTTP-level tests                                                            #
# --------------------------------------------------------------------------- #


class TestHTTP:
    """Same checks as above but routed through TestClient."""

    def test_events_endpoint_default(self, client):
        resp = client.get("/api/activity-feed/events")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_matching"] == 9
        assert body["total_returned"] == 9
        assert len(body["items"]) == 9
        # Composite ID prefixes are visible to the client.
        assert {it["id"].split(":")[0] for it in body["items"]} == {
            "ingest", "usage", "insight",
        }

    def test_events_top_n_query(self, client):
        resp = client.get("/api/activity-feed/events?top_n=2")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_returned"] == 2
        assert body["total_matching"] == 9

    def test_events_kind_filter(self, client):
        resp = client.get("/api/activity-feed/events?kind=agent_call")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_matching"] == 4
        assert all(e["kind"] == "agent_call" for e in body["items"])

    def test_events_severity_filter(self, client):
        resp = client.get("/api/activity-feed/events?severity=critical")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_matching"] == 1
        assert body["items"][0]["kind"] == "ingest_failed"

    def test_events_top_n_validates_bounds(self, client):
        resp = client.get("/api/activity-feed/events?top_n=0")
        assert resp.status_code == 422

    def test_summary_endpoint(self, client):
        resp = client.get("/api/activity-feed/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 9
        assert body["by_severity"]["critical"] == 1
        assert body["by_severity"]["warning"] == 2
        assert body["by_severity"]["info"] == 6
        assert body["by_kind"]["agent_call"] == 4
        assert body["by_kind"]["insight_generated"] == 2
        assert "as_of" in body

    def test_summary_lookback_query(self, client):
        # 1-day lookback shrinks the cohort: ingest_ok (2h),
        # usage J-1001 (30m), usage bid_agent (4h), usage proposal (10h),
        # insight executive_dashboard (1h) = 5.
        resp = client.get("/api/activity-feed/summary?lookback_days=1")
        assert resp.status_code == 200
        assert resp.json()["total"] == 5
