"""FastAPI router for the cost_coding module.

Endpoints (mounted at ``/api/cost-coding`` in ``app.main``):
    GET /summary        KPI tiles.
    GET /list           Paginated, filterable, sortable table.
    GET /insights       Precomputed analytics.
    GET /{code_id}      Detail row for a single cost code.

Cost-code IDs are whitespace-stripped HCSS activity codes. They can
contain dots (e.g. ``1101.100``) but not slashes; the detail route
uses a path converter so codes with dots stay addressable.

Mirrors the equipment / work-orders / timecards / jobs / fleet_pnl /
vendors module pattern: two lightweight dependencies (``get_engine``
and ``get_tenant_id``) so tests can override them via
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
from app.core.llm import InsightResponse
from app.models.tenant import Tenant
from app.modules.cost_coding import insights as insights_pipeline
from app.modules.cost_coding import service
from app.modules.cost_coding.schema import (
    CostCategory,
    CostCodeDetail,
    CostCodeListResponse,
    CostCodingInsights,
    CostCodingSummary,
    CostSizeTier,
    UsageTier,
)

log = logging.getLogger("fieldbridge.cost_coding")

router = APIRouter()


# --------------------------------------------------------------------------- #
# Dependencies (overridable in tests)                                         #
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def _default_engine() -> Engine:
    """Process-wide sync engine for mart reads.

    ``dependency_overrides`` in tests injects a test-specific engine,
    so this cache never becomes a problem in the test suite.
    """
    return create_engine(_sync_url(settings.database_url), pool_pre_ping=True)


def get_engine() -> Engine:
    """Default engine dependency. Override in tests."""
    return _default_engine()


def get_tenant_id(engine: Engine = Depends(get_engine)) -> str:
    """Resolve the request's tenant UUID.

    No auth yet on this module (read-only mart data); we default to
    the ``vancon`` reference tenant. When auth is added, swap this
    for ``app.core.auth.get_current_tenant`` and return ``tenant.id``.
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


@router.get("/summary", response_model=CostCodingSummary)
def summary(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
) -> CostCodingSummary:
    """KPI tiles — totals, per-bucket coverage, uncosted-code gaps."""
    return service.get_summary(engine, tenant_id)


@router.get("/list", response_model=CostCodeListResponse)
def list_(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
    sort_by: Literal[
        "code",
        "estimate_count",
        "total_direct_cost",
        "total_man_hours",
        "labor_cost",
        "equipment_cost",
        "subcontract_cost",
    ] = "total_direct_cost",
    sort_dir: Literal["asc", "desc"] = "desc",
    cost_category: CostCategory | None = Query(
        None, description="Filter by dominant cost category.",
    ),
    size_tier: CostSizeTier | None = Query(
        None, description="Filter by dollar-magnitude tier.",
    ),
    usage_tier: UsageTier | None = Query(
        None, description="Filter by distinct-estimate-count tier.",
    ),
    major_code: str | None = Query(
        None,
        description=(
            "Filter by pre-dot major-code prefix (e.g. ``1101``). "
            "Exact match."
        ),
        max_length=40,
    ),
    search: str | None = Query(
        None,
        description=(
            "Case-insensitive substring match on code or description."
        ),
    ),
    category_dominance: float = Query(
        service.DEFAULT_CATEGORY_DOMINANCE_THRESHOLD,
        ge=0.0, le=1.0,
        description=(
            "Share a single bucket must reach to claim a code's "
            "dominant cost category. Default 0.6."
        ),
    ),
    major_cost_min: float = Query(
        service.DEFAULT_MAJOR_COST_MIN,
        ge=0.0,
        description="Total direct cost to qualify as ``major`` size tier.",
    ),
    significant_cost_min: float = Query(
        service.DEFAULT_SIGNIFICANT_COST_MIN,
        ge=0.0,
        description=(
            "Total direct cost to qualify as ``significant`` size tier."
        ),
    ),
    heavy_min: int = Query(
        service.DEFAULT_HEAVY_MIN_ESTIMATES,
        ge=2,
        description="Distinct estimates for ``heavy`` usage tier.",
    ),
    regular_min: int = Query(
        service.DEFAULT_REGULAR_MIN_ESTIMATES,
        ge=2,
        description="Distinct estimates for ``regular`` usage tier.",
    ),
) -> CostCodeListResponse:
    """Paginated cost-code table with filters, sort, and tier tunables."""
    return service.list_cost_codes(
        engine, tenant_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        cost_category=cost_category,
        size_tier=size_tier,
        usage_tier=usage_tier,
        major_code=major_code,
        search=search,
        category_dominance=category_dominance,
        major_cost_min=major_cost_min,
        significant_cost_min=significant_cost_min,
        heavy_min=heavy_min,
        regular_min=regular_min,
    )


@router.get("/insights", response_model=CostCodingInsights)
def insights(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    top_n: int = Query(
        service.DEFAULT_TOP_N, ge=1, le=100,
        description="How many rows to return in each top-N list.",
    ),
    category_dominance: float = Query(
        service.DEFAULT_CATEGORY_DOMINANCE_THRESHOLD,
        ge=0.0, le=1.0,
    ),
    major_cost_min: float = Query(
        service.DEFAULT_MAJOR_COST_MIN, ge=0.0,
    ),
    significant_cost_min: float = Query(
        service.DEFAULT_SIGNIFICANT_COST_MIN, ge=0.0,
    ),
    heavy_min: int = Query(
        service.DEFAULT_HEAVY_MIN_ESTIMATES, ge=2,
    ),
    regular_min: int = Query(
        service.DEFAULT_REGULAR_MIN_ESTIMATES, ge=2,
    ),
) -> CostCodingInsights:
    """Precomputed analytics: category / size / usage mix, top-N lists."""
    return service.get_insights(
        engine, tenant_id,
        top_n=top_n,
        category_dominance=category_dominance,
        major_cost_min=major_cost_min,
        significant_cost_min=significant_cost_min,
        heavy_min=heavy_min,
        regular_min=regular_min,
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
    """Phase-6 LLM-generated cost-coding recommendations.

    Cached for ``DEFAULT_TTL_HOURS`` (6h) per ``(tenant, module)``;
    re-runs automatically when the underlying cost-coding context changes
    (revision-token mismatch).
    """
    return insights_pipeline.build_recommendations(
        engine, tenant_id, force_refresh=refresh,
    )


# NOTE: ``/{code_id}`` is declared LAST so the literal routes above
# (``/summary``, ``/list``, ``/insights``, ``/recommendations``) aren't
# shadowed by the catch-all path converter.
@router.get("/{code_id:path}", response_model=CostCodeDetail)
def detail(
    code_id: str,
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    detail_estimates: int = Query(
        service.DEFAULT_DETAIL_ESTIMATES, ge=1, le=500,
        description="How many per-estimate breakdown rows to return.",
    ),
    category_dominance: float = Query(
        service.DEFAULT_CATEGORY_DOMINANCE_THRESHOLD,
        ge=0.0, le=1.0,
    ),
    major_cost_min: float = Query(
        service.DEFAULT_MAJOR_COST_MIN, ge=0.0,
    ),
    significant_cost_min: float = Query(
        service.DEFAULT_SIGNIFICANT_COST_MIN, ge=0.0,
    ),
    heavy_min: int = Query(
        service.DEFAULT_HEAVY_MIN_ESTIMATES, ge=2,
    ),
    regular_min: int = Query(
        service.DEFAULT_REGULAR_MIN_ESTIMATES, ge=2,
    ),
) -> CostCodeDetail:
    """Detail view for a single cost code."""
    result = service.get_cost_code_detail(
        engine, tenant_id, code_id,
        detail_estimates=detail_estimates,
        category_dominance=category_dominance,
        major_cost_min=major_cost_min,
        significant_cost_min=significant_cost_min,
        heavy_min=heavy_min,
        regular_min=regular_min,
    )
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown cost code: {code_id!r}"
        )
    return result
