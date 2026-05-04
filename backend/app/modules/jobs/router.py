"""FastAPI router for the jobs module.

Endpoints (mounted at ``/api/jobs`` in ``app.main``):
    GET /summary      KPI tiles.
    GET /list         Paginated, filterable, sortable table.
    GET /{job_id}     Detail row (WIP + schedule + estimate history).
    GET /insights     Precomputed analytics.

Job IDs are stripped descriptions (e.g. ``2231. UDOT Bangerter``).
Because the mart stores ``' 2231. UDOT Bangerter'`` with a leading
space, the service layer normalizes both sides when looking up; the
API exposes only the stripped form.

Mirrors the equipment / work-orders / timecards module pattern: two
lightweight dependencies (``get_engine`` and ``get_tenant_id``) so
tests can override them via ``app.dependency_overrides``.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine, create_engine

from app.core.config import settings
from app.core.ingest import _sync_url
from app.modules.dependencies import get_tenant_id
from app.core.llm import InsightResponse
from app.modules.jobs import insights as insights_pipeline
from app.modules.jobs import service
from app.modules.jobs.schema import (
    BillingStatus,
    FinancialStatus,
    JobDetail,
    JobListResponse,
    JobSummary,
    JobsInsights,
    ScheduleStatus,
)

log = logging.getLogger("fieldbridge.jobs")

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



# --------------------------------------------------------------------------- #
# Endpoints                                                                   #
# --------------------------------------------------------------------------- #


@router.get("/summary", response_model=JobSummary)
def summary(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    at_risk_days: int = Query(
        service.DEFAULT_AT_RISK_DAYS, ge=1, le=365,
        description="Days-until-proj_end window classified as at_risk.",
    ),
    breakeven_band_pct: float = Query(
        service.DEFAULT_BREAKEVEN_BAND_PCT, ge=0.0, le=100.0,
        description="± margin-% band classified as breakeven.",
    ),
    billing_balance_pct: float = Query(
        service.DEFAULT_BILLING_BALANCE_PCT, ge=0.0, le=100.0,
        description="|over_under_billings| / contract tolerance for balanced.",
    ),
) -> JobSummary:
    """KPI tiles — totals, schedule/financial/billing breakdowns, margin."""
    return service.get_summary(
        engine, tenant_id,
        at_risk_days=at_risk_days,
        breakeven_band_pct=breakeven_band_pct,
        billing_balance_pct=billing_balance_pct,
    )


@router.get("/list", response_model=JobListResponse)
def list_(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
    sort_by: Literal[
        "job", "priority", "proj_end", "percent_complete",
        "total_contract", "contract_cost_td", "est_gross_profit",
        "est_gross_profit_pct", "gross_profit_pct_td",
        "over_under_billings", "schedule_days_to_end",
    ] = "priority",
    sort_dir: Literal["asc", "desc"] = "asc",
    schedule_status: ScheduleStatus | None = Query(
        None, description="Filter by schedule status."
    ),
    financial_status: FinancialStatus | None = Query(
        None, description="Filter by financial status."
    ),
    billing_status: BillingStatus | None = Query(
        None, description="Filter by billing status."
    ),
    search: str | None = Query(
        None, description="Case-insensitive substring match on job text.",
    ),
    at_risk_days: int = Query(
        service.DEFAULT_AT_RISK_DAYS, ge=1, le=365,
        description="Days-until-proj_end window classified as at_risk.",
    ),
    breakeven_band_pct: float = Query(
        service.DEFAULT_BREAKEVEN_BAND_PCT, ge=0.0, le=100.0,
        description="± margin-% band classified as breakeven.",
    ),
    billing_balance_pct: float = Query(
        service.DEFAULT_BILLING_BALANCE_PCT, ge=0.0, le=100.0,
        description="|over_under_billings| / contract tolerance for balanced.",
    ),
) -> JobListResponse:
    """Paginated job table with filters and sort."""
    return service.list_jobs(
        engine, tenant_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        schedule_status=schedule_status,
        financial_status=financial_status,
        billing_status=billing_status,
        search=search,
        at_risk_days=at_risk_days,
        breakeven_band_pct=breakeven_band_pct,
        billing_balance_pct=billing_balance_pct,
    )


@router.get("/insights", response_model=JobsInsights)
def insights(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    at_risk_days: int = Query(
        service.DEFAULT_AT_RISK_DAYS, ge=1, le=365,
        description="Days-until-proj_end window classified as at_risk.",
    ),
    breakeven_band_pct: float = Query(
        service.DEFAULT_BREAKEVEN_BAND_PCT, ge=0.0, le=100.0,
        description="± margin-% band classified as breakeven.",
    ),
    billing_balance_pct: float = Query(
        service.DEFAULT_BILLING_BALANCE_PCT, ge=0.0, le=100.0,
        description="|over_under_billings| / contract tolerance for balanced.",
    ),
    top_n: int = Query(
        service.DEFAULT_TOP_N, ge=1, le=100,
        description="How many rows to return in each top-N list.",
    ),
) -> JobsInsights:
    """Precomputed analytics: schedule + financial + billing + estimate accuracy."""
    return service.get_insights(
        engine, tenant_id,
        at_risk_days=at_risk_days,
        breakeven_band_pct=breakeven_band_pct,
        billing_balance_pct=billing_balance_pct,
        top_n=top_n,
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
    """Phase-6 LLM-generated job-performance recommendations.

    Cached for ``DEFAULT_TTL_HOURS`` (6h) per ``(tenant, module)``;
    re-runs automatically when the underlying jobs context changes
    (revision-token mismatch).
    """
    return insights_pipeline.build_recommendations(
        engine, tenant_id, force_refresh=refresh,
    )


# NOTE: ``/{job_id}`` is declared LAST so the literal routes above
# (``/summary``, ``/list``, ``/insights``, ``/recommendations``) aren't
# shadowed by the catch-all.
@router.get("/{job_id:path}", response_model=JobDetail)
def detail(
    job_id: str,
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    at_risk_days: int = Query(
        service.DEFAULT_AT_RISK_DAYS, ge=1, le=365,
        description="Days-until-proj_end window classified as at_risk.",
    ),
    breakeven_band_pct: float = Query(
        service.DEFAULT_BREAKEVEN_BAND_PCT, ge=0.0, le=100.0,
        description="± margin-% band classified as breakeven.",
    ),
    billing_balance_pct: float = Query(
        service.DEFAULT_BILLING_BALANCE_PCT, ge=0.0, le=100.0,
        description="|over_under_billings| / contract tolerance for balanced.",
    ),
) -> JobDetail:
    """Detail view for a single job (WIP + schedule + estimate history)."""
    result = service.get_job_detail(
        engine, tenant_id, job_id,
        at_risk_days=at_risk_days,
        breakeven_band_pct=breakeven_band_pct,
        billing_balance_pct=billing_balance_pct,
    )
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown job: {job_id!r}"
        )
    return result
