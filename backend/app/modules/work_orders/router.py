"""FastAPI router for the work-orders module.

Endpoints (mounted at ``/api/work-orders`` in ``app.main``):
    GET /summary          KPI tiles.
    GET /list             Paginated, filterable, sortable table.
    GET /{work_order}     Detail row.
    GET /insights         Precomputed analytics.

Mirrors the equipment-module pattern: two lightweight dependencies
(``get_engine`` and ``get_tenant_id``) so tests can override them via
``app.dependency_overrides`` without mocking SQL. In production they
resolve to a sync SQLAlchemy engine derived from
``settings.database_url`` and the ``vancon`` tenant UUID.
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
from app.modules.work_orders import insights as insights_pipeline
from app.modules.work_orders import service
from app.modules.work_orders.schema import (
    WorkOrderDetail,
    WorkOrderInsights,
    WorkOrderListResponse,
    WorkOrderPriority,
    WorkOrderStatus,
    WorkOrderSummary,
)

log = logging.getLogger("fieldbridge.work_orders")

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


@router.get("/summary", response_model=WorkOrderSummary)
def summary(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    overdue_days: int = Query(
        service.DEFAULT_OVERDUE_DAYS, ge=1, le=365,
        description="Days after which an open WO is considered overdue.",
    ),
) -> WorkOrderSummary:
    """KPI tiles — totals, status counts, overdue, avg age, cost vs budget."""
    return service.get_summary(engine, tenant_id, overdue_days=overdue_days)


@router.get("/list", response_model=WorkOrderListResponse)
def list_(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
    sort_by: Literal[
        "work_order", "equipment", "status", "priority",
        "open_date", "closed_date", "age_days", "total_cost",
    ] = "open_date",
    sort_dir: Literal["asc", "desc"] = "desc",
    status: WorkOrderStatus | None = Query(
        None, description="Filter to a single status."
    ),
    priority: WorkOrderPriority | None = Query(
        None, description="Filter to a single priority."
    ),
    equipment: str | None = Query(
        None, description="Exact match on equipment name (case-insensitive)."
    ),
    mechanic: str | None = Query(
        None, description="Exact match on assigned mechanic (case-insensitive)."
    ),
    overdue: bool | None = Query(
        None,
        description=(
            "True → overdue WOs only. False → non-overdue only. "
            "Omit for no filter."
        ),
    ),
    search: str | None = Query(
        None,
        description=(
            "Case-insensitive substring match on work_order / equipment / "
            "description / mechanic / requested_by / job_number."
        ),
    ),
    overdue_days: int = Query(
        service.DEFAULT_OVERDUE_DAYS, ge=1, le=365,
        description="Days after which an open WO is considered overdue.",
    ),
) -> WorkOrderListResponse:
    """Paginated work-order table with filters and sort."""
    return service.list_work_orders(
        engine,
        tenant_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        status=status,
        priority=priority,
        equipment=equipment,
        mechanic=mechanic,
        overdue=overdue,
        search=search,
        overdue_days=overdue_days,
    )


@router.get("/insights", response_model=WorkOrderInsights)
def insights(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    overdue_days: int = Query(
        service.DEFAULT_OVERDUE_DAYS, ge=1, le=365,
        description="Days after which an open WO is considered overdue.",
    ),
) -> WorkOrderInsights:
    """Precomputed analytics: status counts, avg age, overdue, cost vs budget."""
    return service.get_insights(engine, tenant_id, overdue_days=overdue_days)


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
    """Phase-6 LLM-generated work-order recommendations.

    Cached for ``DEFAULT_TTL_HOURS`` (6h) per ``(tenant, module)``;
    re-runs automatically when the underlying work-order context changes
    (revision-token mismatch).
    """
    return insights_pipeline.build_recommendations(
        engine, tenant_id, force_refresh=refresh,
    )


# NOTE: ``/{work_order}`` is declared LAST so the literal routes above
# (``/summary``, ``/list``, ``/insights``, ``/recommendations``) aren't
# shadowed by the catch-all.
@router.get("/{work_order}", response_model=WorkOrderDetail)
def detail(
    work_order: str,
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    overdue_days: int = Query(
        service.DEFAULT_OVERDUE_DAYS, ge=1, le=365,
        description="Days after which an open WO is considered overdue.",
    ),
) -> WorkOrderDetail:
    """Detail view for a single work order (keyed by WO number)."""
    result = service.get_work_order_detail(
        engine, tenant_id, work_order, overdue_days=overdue_days,
    )
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown work order: {work_order!r}"
        )
    return result
