"""FastAPI router for the fleet_pnl module.

Endpoints (mounted at ``/api/fleet-pnl`` in ``app.main``):
    GET /summary       KPI tiles.
    GET /list          Paginated, filterable, sortable truck table.
    GET /{truck_id}    Detail row (rollup + recent tickets + mixes).
    GET /insights      Precomputed analytics.

Truck IDs are the raw truck tag (e.g. ``TK149``). The detail route
uses the path converter for forward compatibility with any future
tags that include slashes — today's data is slash-free.

Mirrors the equipment / work-orders / timecards / jobs module
pattern: two lightweight dependencies (``get_engine`` and
``get_tenant_id``) so tests can override them via
``app.dependency_overrides``.
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
from app.models.tenant import Tenant
from app.modules.fleet_pnl import service
from app.modules.fleet_pnl.schema import (
    FleetPnlInsights,
    FleetSummary,
    FleetTruckDetail,
    InvoiceBucket,
    LessorFlag,
    TruckListResponse,
    UtilizationBucket,
)

log = logging.getLogger("fieldbridge.fleet_pnl")

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


@router.get("/summary", response_model=FleetSummary)
def summary(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    underutilized_max_tickets: int = Query(
        service.DEFAULT_UNDERUTILIZED_MAX_TICKETS, ge=0, le=100_000,
        description="ticket_count <= this is ``underutilized``.",
    ),
    heavily_utilized_min_tickets: int = Query(
        service.DEFAULT_HEAVILY_UTILIZED_MIN_TICKETS, ge=1, le=100_000,
        description="ticket_count >= this is ``heavily_utilized``.",
    ),
) -> FleetSummary:
    """KPI tiles — totals, invoicing, ownership mix, rental-in cost."""
    return service.get_summary(
        engine, tenant_id,
        underutilized_max_tickets=underutilized_max_tickets,
        heavily_utilized_min_tickets=heavily_utilized_min_tickets,
    )


@router.get("/list", response_model=TruckListResponse)
def list_(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
    sort_by: Literal[
        "truck", "ticket_count", "revenue", "uninvoiced_revenue",
        "invoiced_revenue", "total_qty", "invoice_rate",
        "jobs_served", "vendors_served", "last_ticket",
    ] = "revenue",
    sort_dir: Literal["asc", "desc"] = "desc",
    lessor_flag: LessorFlag | None = Query(
        None, description="Filter by ownership.",
    ),
    invoice_bucket: InvoiceBucket | None = Query(
        None, description="Filter by invoicing completeness.",
    ),
    utilization_bucket: UtilizationBucket | None = Query(
        None, description="Filter by ticket-volume tier.",
    ),
    search: str | None = Query(
        None,
        description=(
            "Case-insensitive substring match on truck tag, top vendor, "
            "top material, top driver, or top job."
        ),
    ),
    underutilized_max_tickets: int = Query(
        service.DEFAULT_UNDERUTILIZED_MAX_TICKETS, ge=0, le=100_000,
    ),
    heavily_utilized_min_tickets: int = Query(
        service.DEFAULT_HEAVILY_UTILIZED_MIN_TICKETS, ge=1, le=100_000,
    ),
) -> TruckListResponse:
    """Paginated truck table with filters and sort."""
    return service.list_trucks(
        engine, tenant_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        lessor_flag=lessor_flag,
        invoice_bucket=invoice_bucket,
        utilization_bucket=utilization_bucket,
        search=search,
        underutilized_max_tickets=underutilized_max_tickets,
        heavily_utilized_min_tickets=heavily_utilized_min_tickets,
    )


@router.get("/insights", response_model=FleetPnlInsights)
def insights(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    underutilized_max_tickets: int = Query(
        service.DEFAULT_UNDERUTILIZED_MAX_TICKETS, ge=0, le=100_000,
    ),
    heavily_utilized_min_tickets: int = Query(
        service.DEFAULT_HEAVILY_UTILIZED_MIN_TICKETS, ge=1, le=100_000,
    ),
    top_n: int = Query(
        service.DEFAULT_TOP_N, ge=1, le=100,
        description="How many rows to return in each top-N list.",
    ),
) -> FleetPnlInsights:
    """Precomputed analytics: utilization + invoicing buckets, top-N lists, rental-in."""
    return service.get_insights(
        engine, tenant_id,
        underutilized_max_tickets=underutilized_max_tickets,
        heavily_utilized_min_tickets=heavily_utilized_min_tickets,
        top_n=top_n,
    )


# NOTE: ``/{truck_id}`` is declared LAST so the literal routes above
# (``/summary``, ``/list``, ``/insights``) aren't shadowed by the catch-all.
@router.get("/{truck_id:path}", response_model=FleetTruckDetail)
def detail(
    truck_id: str,
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    underutilized_max_tickets: int = Query(
        service.DEFAULT_UNDERUTILIZED_MAX_TICKETS, ge=0, le=100_000,
    ),
    heavily_utilized_min_tickets: int = Query(
        service.DEFAULT_HEAVILY_UTILIZED_MIN_TICKETS, ge=1, le=100_000,
    ),
    recent_limit: int = Query(
        service.DEFAULT_RECENT_TICKETS, ge=1, le=200,
        description="How many most-recent tickets to include.",
    ),
    mix_limit: int = Query(
        service.DEFAULT_MIX_LIMIT, ge=1, le=50,
        description="Rows per vendor/material/job/driver mix.",
    ),
) -> FleetTruckDetail:
    """Detail view for a single truck (rollup + recent tickets + mixes)."""
    result = service.get_truck_detail(
        engine, tenant_id, truck_id,
        underutilized_max_tickets=underutilized_max_tickets,
        heavily_utilized_min_tickets=heavily_utilized_min_tickets,
        recent_limit=recent_limit,
        mix_limit=mix_limit,
    )
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown truck: {truck_id!r}"
        )
    return result
