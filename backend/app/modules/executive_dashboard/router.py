"""FastAPI router for the executive_dashboard module.

Endpoints (mounted at ``/api/executive-dashboard`` in ``app.main``):

    GET /summary        Cross-module KPI tile rollup (financial / ops /
                        pipeline / roster).
    GET /attention      Top-N flagged jobs needing CFO/owner eyes.
    GET /trend          Trailing 12-month revenue trend for sparkline.

Mirrors the dependency-override pattern used by the equipment / jobs
modules — ``get_engine`` and ``get_tenant_id`` are tiny wrappers that
tests replace via ``app.dependency_overrides`` so we never need to
mock SQL.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine, create_engine

from app.core.config import settings
from app.core.ingest import _sync_url
from app.modules.dependencies import get_tenant_id
from app.modules.executive_dashboard import service
from app.modules.executive_dashboard.schema import (
    ExecutiveAttention,
    ExecutiveSummary,
    ExecutiveTrend,
)

log = logging.getLogger("fieldbridge.executive_dashboard")

router = APIRouter()


# --------------------------------------------------------------------------- #
# Dependencies (overridable in tests)                                         #
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def _default_engine() -> Engine:
    """Process-wide sync engine for mart reads."""
    return create_engine(_sync_url(settings.database_url), pool_pre_ping=True)


def get_engine() -> Engine:
    """Default engine dependency. Override in tests."""
    return _default_engine()



# --------------------------------------------------------------------------- #
# Endpoints                                                                   #
# --------------------------------------------------------------------------- #


@router.get("/summary", response_model=ExecutiveSummary)
def summary(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
) -> ExecutiveSummary:
    """KPI tile rollup across financial / ops / pipeline / roster."""
    return service.get_summary(engine, tenant_id)


@router.get("/attention", response_model=ExecutiveAttention)
def attention(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    top_n: int = Query(
        10,
        ge=1,
        le=50,
        description=(
            "How many flagged items to return. Items are sorted by "
            "severity (largest first) regardless of axis."
        ),
    ),
) -> ExecutiveAttention:
    """Top-N flagged jobs across margin / schedule / billing axes."""
    return service.get_attention(engine, tenant_id, top_n=top_n)


@router.get("/trend", response_model=ExecutiveTrend)
def trend(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    months: int = Query(
        12,
        ge=1,
        le=36,
        description="Number of trailing months to include in the trend.",
    ),
) -> ExecutiveTrend:
    """Trailing-N-months estimate vs. actual sparkline data."""
    return service.get_trend(engine, tenant_id, months=months)
