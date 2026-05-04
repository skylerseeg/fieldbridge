"""FastAPI router for the productivity module.

Endpoints (mounted at ``/api/productivity`` in ``app.main``):
    GET /summary             KPI tiles (totals + status counts).
    GET /attention           Phases needing attention, sorted by severity.
    GET /jobs/{job_id:path}  Phase grid + labor/equipment rollups for one job.

Job IDs in the URL are stripped (whitespace-collapsed). The mart stores
the raw label (e.g. " 2321. - CUWCD Santaquin Reach"); the service
layer normalizes both sides on lookup.

Dependencies (``get_engine``, ``get_tenant_id``) mirror the jobs / equipment
modules so the test suite can override them via ``app.dependency_overrides``.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine, create_engine

from app.core.config import settings
from app.core.ingest import _sync_url
from app.modules.dependencies import get_tenant_id
from app.modules.productivity import service
from app.modules.productivity.schema import (
    JobProductivityDetail,
    PhaseStatus,
    ProductivityAttention,
    ProductivitySummary,
    ResourceKind,
)

log = logging.getLogger("fieldbridge.productivity")

router = APIRouter()


# --------------------------------------------------------------------------- #
# Dependencies                                                                #
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def _default_engine() -> Engine:
    return create_engine(_sync_url(settings.database_url), pool_pre_ping=True)


def get_engine() -> Engine:
    """Default engine dependency. Override in tests."""
    return _default_engine()



# --------------------------------------------------------------------------- #
# Endpoints                                                                   #
# --------------------------------------------------------------------------- #


@router.get("/summary", response_model=ProductivitySummary)
def summary(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    pace_band_pct: float = Query(
        service.DEFAULT_PACE_BAND_PCT, ge=0.0, le=100.0,
        description=(
            "± band around (pct_used == pct_complete) classified as "
            "on track. 10 means a phase that has used 10pp more of its "
            "budget than its progress is BEHIND_PACE."
        ),
    ),
) -> ProductivitySummary:
    """Productivity KPI tiles — totals, status counts, percent-used."""
    return service.get_summary(
        engine, tenant_id, pace_band_pct=pace_band_pct,
    )


@router.get("/attention", response_model=ProductivityAttention)
def attention(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    pace_band_pct: float = Query(
        service.DEFAULT_PACE_BAND_PCT, ge=0.0, le=100.0,
        description="See /summary.",
    ),
    resource_kind: ResourceKind | None = Query(
        None,
        description="Filter by resource: 'labor' or 'equipment'.",
    ),
    status: PhaseStatus | None = Query(
        None,
        description=(
            "Filter by phase status. Only OVER_BUDGET and BEHIND_PACE rows "
            "appear in the attention list; other values return an empty set."
        ),
    ),
    top_n: int = Query(
        service.DEFAULT_TOP_N, ge=1, le=500,
        description="Cap the items list (sorted by severity desc).",
    ),
) -> ProductivityAttention:
    """Phases needing PM attention — over budget or behind pace."""
    return service.get_attention(
        engine, tenant_id,
        pace_band_pct=pace_band_pct,
        resource_kind=resource_kind,
        status=status,
        top_n=top_n,
    )


# NOTE: ``/jobs/{job_id:path}`` is declared LAST so the literal routes
# above (``/summary``, ``/attention``) aren't shadowed.
@router.get("/jobs/{job_id:path}", response_model=JobProductivityDetail)
def job_detail(
    job_id: str,
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    pace_band_pct: float = Query(
        service.DEFAULT_PACE_BAND_PCT, ge=0.0, le=100.0,
        description="See /summary.",
    ),
) -> JobProductivityDetail:
    """Phase grid for one job — labor + equipment side by side, plus rollups."""
    result = service.get_job_detail(
        engine, tenant_id, job_id, pace_band_pct=pace_band_pct,
    )
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown job: {job_id!r}"
        )
    return result
