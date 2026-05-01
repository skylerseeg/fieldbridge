"""FastAPI router for the timecards module.

Endpoints (mounted at ``/api/timecards`` in ``app.main``):
    GET /summary          KPI tiles.
    GET /list             Paginated, filterable, sortable table.
    GET /{class_name}     Detail row (monthly breakdown).
    GET /insights         Precomputed analytics.

Mirrors the equipment / work-orders module pattern: two lightweight
dependencies (``get_engine`` and ``get_tenant_id``) so tests can
override them via ``app.dependency_overrides`` without mocking SQL.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.ingest import _sync_url
from app.core.llm import InsightResponse
from app.models.tenant import Tenant
from app.modules.timecards import insights as insights_pipeline
from app.modules.timecards import service
from app.modules.timecards.schema import (
    TimecardDetail,
    TimecardInsights,
    TimecardListResponse,
    TimecardSummary,
    VarianceStatus,
)

log = logging.getLogger("fieldbridge.timecards")

router = APIRouter()


# --------------------------------------------------------------------------- #
# Dependencies (overridable in tests)                                         #
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def _default_engine() -> Engine:
    """Process-wide sync engine for mart reads.

    ``dependency_overrides`` in tests injects a test-specific engine, so
    this cache never becomes a problem in the test suite.
    """
    return create_engine(_sync_url(settings.database_url), pool_pre_ping=True)


def get_engine() -> Engine:
    """Default engine dependency. Override in tests."""
    return _default_engine()


def get_tenant_id(engine: Engine = Depends(get_engine)) -> str:
    """Resolve the request's tenant UUID.

    No auth yet on this module (read-only mart data); we default to the
    ``vancon`` reference tenant. When auth is added, swap this for
    ``app.core.auth.get_current_tenant`` and return ``tenant.id``.
    """
    SessionLocal = sessionmaker(engine)
    with SessionLocal() as s:
        tenant = s.execute(
            select(Tenant).where(Tenant.slug == "vancon")
        ).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(
            status_code=503,
            detail="Reference tenant not seeded. Run scripts/create_mart_tables.py.",
        )
    return tenant.id


# --------------------------------------------------------------------------- #
# Endpoints                                                                   #
# --------------------------------------------------------------------------- #


@router.get("/summary", response_model=TimecardSummary)
def summary(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    band_pct: float = Query(
        service.DEFAULT_VARIANCE_BAND_PCT, ge=0.0, le=100.0,
        description="± band (percentage points) for variance_status=on_track.",
    ),
) -> TimecardSummary:
    """KPI tiles — totals, variance, overtime, overhead ratio."""
    return service.get_summary(engine, tenant_id, band_pct=band_pct)


@router.get("/list", response_model=TimecardListResponse)
def list_(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
    sort_by: Literal[
        "class_name", "actual_avg_fte", "projected_avg_fte",
        "variance", "variance_pct", "overtime_pct",
        "monthly_hours", "last_month_actuals",
    ] = "variance_pct",
    sort_dir: Literal["asc", "desc"] = "desc",
    status: VarianceStatus | None = Query(
        None, description="Filter to a single variance status."
    ),
    search: str | None = Query(
        None,
        description=(
            "Case-insensitive substring match on class_name / code / "
            "craft_class."
        ),
    ),
    overtime_only: bool | None = Query(
        None,
        description=(
            "True → only classes with overtime_hours > 0. False → only "
            "classes with no overtime. Omit for no filter."
        ),
    ),
    band_pct: float = Query(
        service.DEFAULT_VARIANCE_BAND_PCT, ge=0.0, le=100.0,
        description="± band (percentage points) for variance_status=on_track.",
    ),
) -> TimecardListResponse:
    """Paginated timecards table with filters and sort."""
    return service.list_timecards(
        engine,
        tenant_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        status=status,
        search=search,
        overtime_only=overtime_only,
        band_pct=band_pct,
    )


@router.get("/insights", response_model=TimecardInsights)
def insights(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    band_pct: float = Query(
        service.DEFAULT_VARIANCE_BAND_PCT, ge=0.0, le=100.0,
        description="± band (percentage points) for variance_status=on_track.",
    ),
    top_n: int = Query(
        service.DEFAULT_TOP_N, ge=1, le=100,
        description="How many classes to include in each insight list.",
    ),
) -> TimecardInsights:
    """Precomputed analytics: variance (over/under), overtime, overhead ratio."""
    return service.get_insights(
        engine, tenant_id, band_pct=band_pct, top_n=top_n,
    )


@router.get("/recommendations", response_model=InsightResponse)
def recommendations(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    refresh: bool = Query(
        False,
        description=(
            "Bypass the 6h cache and force a fresh Claude call. Used by "
            "the admin Regenerate button — most callers should leave this "
            "false."
        ),
    ),
) -> InsightResponse:
    """Phase-6 LLM-generated timecard/FTE recommendations.

    Cached for ``DEFAULT_TTL_HOURS`` (6h) per ``(tenant, module)``;
    re-runs automatically when the underlying timecard context changes
    (revision-token mismatch).
    """
    return insights_pipeline.build_recommendations(
        engine, tenant_id, force_refresh=refresh,
    )


# NOTE: ``/{class_name}`` is declared LAST so the literal routes above
# (``/summary``, ``/list``, ``/insights``, ``/recommendations``) aren't
# shadowed by the catch-all.
@router.get("/{class_name}", response_model=TimecardDetail)
def detail(
    class_name: str,
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    band_pct: float = Query(
        service.DEFAULT_VARIANCE_BAND_PCT, ge=0.0, le=100.0,
        description="± band (percentage points) for variance_status=on_track.",
    ),
) -> TimecardDetail:
    """Detail view for a single job class (monthly breakdown)."""
    result = service.get_timecard_detail(
        engine, tenant_id, class_name, band_pct=band_pct,
    )
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown job class: {class_name!r}"
        )
    return result
