"""FastAPI router for the activity_feed module.

Endpoints (mounted at ``/api/activity-feed`` in ``app.main``):

    GET /events    Severity-ranked, paginated merge of ingest_log /
                   usage_events / llm_insights for the tenant.
    GET /summary   Tile-strip rollup: counts by severity, kind, and
                   trailing-window cohorts (24h / 7d / total).

Mirrors the dependency-override pattern used by the executive_dashboard
module — ``get_engine`` and ``get_tenant_id`` are tiny wrappers that
tests replace via ``app.dependency_overrides`` so we never need to
mock SQL.
"""
from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine, create_engine

from app.core.config import settings
from app.core.ingest import _sync_url
from app.modules.dependencies import get_tenant_id
from app.modules.activity_feed import service
from app.modules.activity_feed.schema import (
    ActivityFeed,
    ActivityKind,
    ActivitySeverity,
    ActivitySummary,
)


log = logging.getLogger("fieldbridge.activity_feed")

router = APIRouter()


# --------------------------------------------------------------------------- #
# Dependencies (overridable in tests)                                         #
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def _default_engine() -> Engine:
    """Process-wide sync engine for event reads."""
    return create_engine(_sync_url(settings.database_url), pool_pre_ping=True)


def get_engine() -> Engine:
    """Default engine dependency. Override in tests."""
    return _default_engine()



# --------------------------------------------------------------------------- #
# Endpoints                                                                   #
# --------------------------------------------------------------------------- #


@router.get("/events", response_model=ActivityFeed)
def events(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    top_n: int = Query(
        service.DEFAULT_TOP_N,
        ge=1,
        le=service.MAX_TOP_N,
        description=(
            "How many events to return after filtering. Items are "
            "sorted (severity desc, occurred_at desc); the pre-cap "
            "count is reported in ``total_matching``."
        ),
    ),
    lookback_days: int = Query(
        service.DEFAULT_LOOKBACK_DAYS,
        ge=1,
        le=service.MAX_LOOKBACK_DAYS,
        description=(
            "Trailing window (days). Ignored when ``since`` is "
            "supplied. Default keeps the feed in step with the "
            "executive dashboard's 30-day window."
        ),
    ),
    since: datetime | None = Query(
        None,
        description=(
            "Explicit lower bound (UTC) for the event window. When "
            "supplied, overrides ``lookback_days``."
        ),
    ),
    kind: ActivityKind | None = Query(
        None, description="Optional filter on event kind.",
    ),
    severity: ActivitySeverity | None = Query(
        None, description="Optional filter on event severity.",
    ),
) -> ActivityFeed:
    """Severity-ranked merge of the three source streams."""
    return service.get_feed(
        engine,
        tenant_id,
        top_n=top_n,
        lookback_days=lookback_days,
        since=since,
        kind=kind,
        severity=severity,
    )


@router.get("/summary", response_model=ActivitySummary)
def summary(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    lookback_days: int = Query(
        service.DEFAULT_LOOKBACK_DAYS,
        ge=1,
        le=service.MAX_LOOKBACK_DAYS,
        description=(
            "Trailing window (days) for the ``total`` and ``by_*`` "
            "counts. ``last_24h`` and ``last_7d`` always use their "
            "named windows regardless of this value."
        ),
    ),
) -> ActivitySummary:
    """Tile-strip rollup at the top of the Activity Feed page."""
    return service.get_summary(
        engine, tenant_id, lookback_days=lookback_days,
    )
