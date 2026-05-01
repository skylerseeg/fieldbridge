"""FastAPI router for the equipment module.

Endpoints (mounted at ``/api/equipment`` in ``app.main``):
    GET /summary          KPI tiles.
    GET /list             Paginated, filterable, sortable table.
    GET /{asset_id}       Detail row.
    GET /insights         Precomputed analytics.

Two lightweight dependencies — ``get_engine`` and ``get_tenant_id`` — are
used so tests can override them via ``app.dependency_overrides`` without
mocking SQL. In production they resolve to a sync SQLAlchemy engine
derived from ``settings.database_url`` and the ``vancon`` tenant UUID.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.ingest import _sync_url  # best existing sync-url normalizer
from app.core.llm import InsightResponse
from app.models.tenant import Tenant
from app.modules.equipment import insights as insights_pipeline
from app.modules.equipment import service
from app.modules.equipment.schema import (
    EquipmentDetail,
    EquipmentInsights,
    EquipmentListResponse,
    EquipmentStatusResponse,
    EquipmentSummary,
    OwnershipKind,
    UtilizationBucket,
)

log = logging.getLogger("fieldbridge.equipment")

router = APIRouter()


# --------------------------------------------------------------------------- #
# Dependencies (overridable in tests)                                         #
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def _default_engine() -> Engine:
    """Process-wide sync engine for mart reads.

    Cached with ``lru_cache`` so we don't churn connections across requests.
    ``dependency_overrides`` in tests injects a test-specific engine, so
    this cache never becomes a problem.
    """
    return create_engine(_sync_url(settings.database_url), pool_pre_ping=True)


def get_engine() -> Engine:
    """Default engine dependency. Override in tests."""
    return _default_engine()


def get_tenant_id(engine: Engine = Depends(get_engine)) -> str:
    """Resolve the request's tenant UUID.

    No auth yet on this module (it's read-only mart data); we default to
    the ``vancon`` reference tenant. When auth is added, swap this for
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


@router.get("/summary", response_model=EquipmentSummary)
def summary(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
) -> EquipmentSummary:
    """KPI tiles — total assets + 30-day activity + four utilization buckets."""
    return service.get_summary(engine, tenant_id)


@router.get("/list", response_model=EquipmentListResponse)
def list_(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
    sort_by: Literal[
        "truck", "tickets", "total_qty", "total_revenue", "last_ticket_date"
    ] = "last_ticket_date",
    sort_dir: Literal["asc", "desc"] = "desc",
    search: str | None = Query(
        None,
        description="Case-insensitive substring match on truck/equipment name.",
    ),
    bucket: UtilizationBucket | None = Query(
        None, description="Filter to a single utilization bucket."
    ),
    ownership: OwnershipKind | None = Query(
        None, description="Filter to owned vs rented."
    ),
) -> EquipmentListResponse:
    """Paginated equipment table with filters and sort."""
    return service.list_equipment(
        engine,
        tenant_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        search=search,
        bucket_filter=bucket,
        ownership_filter=ownership,
    )


@router.get("/insights", response_model=EquipmentInsights)
def insights(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    top_n: int = Query(20, ge=1, le=100,
                       description="How many assets to return in fuel $/hr."),
) -> EquipmentInsights:
    """Precomputed analytics: buckets, fuel $/hr, rental-vs-owned."""
    return service.get_insights(engine, tenant_id, top_n=top_n)


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
    """Phase-6 LLM-generated equipment recommendations.

    Cached for ``DEFAULT_TTL_HOURS`` (6h) per ``(tenant, module)``;
    re-runs automatically when the underlying 30-day mart slice
    changes (revision-token mismatch).
    """
    return insights_pipeline.build_recommendations(
        engine, tenant_id, force_refresh=refresh,
    )


@router.get("/status", response_model=EquipmentStatusResponse)
def status_board(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    search: str | None = Query(
        None,
        description="Case-insensitive substring match on asset/truck name.",
    ),
    bucket: UtilizationBucket | None = Query(
        None, description="Filter to a single utilization bucket."
    ),
    stale_only: bool = Query(
        False,
        description=(
            "Only assets with no mart_equipment_utilization ticket in 14+ "
            "days and no retired_date."
        ),
    ),
    include_retired: bool = Query(
        True,
        description="Include assets marked retired in mart_asset_barcodes.",
    ),
) -> EquipmentStatusResponse:
    """Field-facing status board over utilization, emwo, transfer, retirement marts."""
    return service.get_status_board(
        engine,
        tenant_id,
        page=page,
        page_size=page_size,
        search=search,
        bucket_filter=bucket,
        stale_only=stale_only,
        include_retired=include_retired,
    )


# NOTE: ``/{asset_id}`` is declared LAST so the literal routes above
# (``/summary``, ``/list``, ``/insights``, ``/recommendations``, ``/status``) aren't
# shadowed by the catch-all.
@router.get("/{asset_id}", response_model=EquipmentDetail)
def detail(
    asset_id: str,
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
) -> EquipmentDetail:
    """Detail view for a single asset (keyed by truck/equipment name)."""
    result = service.get_equipment_detail(engine, tenant_id, asset_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown equipment: {asset_id!r}"
        )
    return result
