"""FastAPI router for the predictive_maintenance module.

Endpoints (mounted at ``/api/predictive-maintenance`` in ``app.main``):

    GET  /summary                     KPI tiles.
    GET  /list                        Paginated, filterable list.
    GET  /insights                    Page-body breakdowns + top-N rollups.
    GET  /{prediction_id}             Detail drawer payload.
    POST /{prediction_id}/acknowledge Status -> acknowledged.
    POST /{prediction_id}/schedule    Status -> scheduled (+ scheduled_for).
    POST /{prediction_id}/complete    Status -> completed (terminal).
    POST /{prediction_id}/dismiss     Status -> dismissed (terminal).

Order matters: literal routes (``/summary`` etc.) are declared *before*
the dynamic ``/{prediction_id}`` so they don't get swallowed.

Mirrors the dependency-override pattern used by the activity_feed and
bids modules — ``get_engine`` and ``get_tenant_id`` are tiny wrappers
that tests replace via ``app.dependency_overrides``.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.ingest import _sync_url
from app.models.tenant import Tenant
from app.modules.predictive_maintenance import service
from app.modules.predictive_maintenance.schema import (
    AcknowledgeBody,
    CompleteBody,
    DismissBody,
    FailureMode,
    MaintSource,
    MaintStatus,
    PredictionDetail,
    PredictionListResponse,
    PredictiveMaintenanceInsights,
    PredictiveMaintenanceSummary,
    RiskTier,
    ScheduleBody,
)


log = logging.getLogger("fieldbridge.predictive_maintenance")

router = APIRouter()


# --------------------------------------------------------------------------- #
# Dependencies (overridable in tests)                                         #
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def _default_engine() -> Engine:
    """Process-wide sync engine for mart reads + writes."""
    return create_engine(_sync_url(settings.database_url), pool_pre_ping=True)


def get_engine() -> Engine:
    """Default engine dependency. Override in tests."""
    return _default_engine()


def get_tenant_id(engine: Engine = Depends(get_engine)) -> str:
    """Resolve the request's tenant UUID via the seeded ``vancon`` slug.

    No auth on this surface yet (read-only mart data + 4 mutation
    endpoints scoped to the same tenant). When auth is added, swap for
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
# Reads                                                                       #
# --------------------------------------------------------------------------- #


@router.get("/summary", response_model=PredictiveMaintenanceSummary)
def summary(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
) -> PredictiveMaintenanceSummary:
    """KPI strip — open / overdue / exposure totals."""
    return service.get_summary(engine, tenant_id)


@router.get("/list", response_model=PredictionListResponse)
def list_(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    page: int = Query(1, ge=1),
    page_size: int = Query(
        service.DEFAULT_PAGE_SIZE, ge=1, le=service.MAX_PAGE_SIZE,
    ),
    sort_by: Literal[
        "risk_tier",
        "days_until_due",
        "estimated_repair_cost",
        "estimated_downtime_hours",
        "equipment_label",
        "predicted_failure_date",
        "created_at",
    ] = "risk_tier",
    sort_dir: Literal["asc", "desc"] = "desc",
    risk_tier: RiskTier | None = Query(None),
    status: MaintStatus | None = Query(None),
    source: MaintSource | None = Query(None),
    failure_mode: FailureMode | None = Query(None),
    equipment_id: str | None = Query(None),
    search: str | None = Query(
        None,
        description=(
            "Case-insensitive substring match across equipment label, "
            "equipment id, and recommended action."
        ),
    ),
    overdue_only: bool = Query(
        False,
        description="If true, return only rows where days_until_due < 0.",
    ),
    min_cost: float | None = Query(
        None,
        ge=0,
        description="Minimum estimated_repair_cost. NULLs excluded when set.",
    ),
) -> PredictionListResponse:
    """Paginated, filterable, sortable prediction list."""
    return service.list_predictions(
        engine,
        tenant_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        risk_tier=risk_tier,
        status=status,
        source=source,
        failure_mode=failure_mode,
        equipment_id=equipment_id,
        search=search,
        overdue_only=overdue_only,
        min_cost=min_cost,
    )


@router.get("/insights", response_model=PredictiveMaintenanceInsights)
def insights(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    top_n: int = Query(
        service.DEFAULT_TOP_N, ge=1, le=service.MAX_TOP_N,
    ),
) -> PredictiveMaintenanceInsights:
    """Page-body breakdowns + top-N exposure rollups."""
    return service.get_insights(engine, tenant_id, top_n=top_n)


# --------------------------------------------------------------------------- #
# Detail + mutations                                                          #
# --------------------------------------------------------------------------- #
#
# ``/{prediction_id}`` MUST appear after every literal route above so
# FastAPI's matcher doesn't capture ``/summary`` etc. as a prediction id.


@router.get("/{prediction_id}", response_model=PredictionDetail)
def detail(
    prediction_id: str,
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
) -> PredictionDetail:
    """Detail drawer payload (row + history + recent WOs + evidence)."""
    return service.get_detail(engine, tenant_id, prediction_id)


@router.post(
    "/{prediction_id}/acknowledge", response_model=PredictionDetail,
)
def acknowledge(
    prediction_id: str,
    body: AcknowledgeBody = Body(default_factory=AcknowledgeBody),
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
) -> PredictionDetail:
    """Acknowledge — first triage step, no scheduling commitment yet."""
    return service.acknowledge(
        engine, tenant_id, prediction_id, note=body.note,
    )


@router.post("/{prediction_id}/schedule", response_model=PredictionDetail)
def schedule(
    prediction_id: str,
    body: ScheduleBody,
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
) -> PredictionDetail:
    """Schedule — sets ``scheduled_for`` and moves status to scheduled."""
    return service.schedule(
        engine,
        tenant_id,
        prediction_id,
        scheduled_for=body.scheduled_for,
        note=body.note,
    )


@router.post("/{prediction_id}/complete", response_model=PredictionDetail)
def complete(
    prediction_id: str,
    body: CompleteBody = Body(default_factory=CompleteBody),
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
) -> PredictionDetail:
    """Mark complete — terminal status, no further transitions allowed."""
    return service.complete(
        engine,
        tenant_id,
        prediction_id,
        completed_at=body.completed_at,
        note=body.note,
    )


@router.post("/{prediction_id}/dismiss", response_model=PredictionDetail)
def dismiss(
    prediction_id: str,
    body: DismissBody = Body(default_factory=DismissBody),
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
) -> PredictionDetail:
    """Dismiss — terminal status; reason is logged into the history note."""
    return service.dismiss(
        engine, tenant_id, prediction_id, reason=body.reason,
    )
