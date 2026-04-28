"""FastAPI router for the bids module.

Endpoints (mounted at ``/api/bids`` in ``app.main``):
    GET /summary        KPI tiles.
    GET /list           Paginated, filterable, sortable table.
    GET /insights       Precomputed analytics.
    GET /{bid_id}       Detail row for a single bid.

Bid IDs are synthetic: a 12-hex-char MD5 prefix of
``f"{job}|{bid_date_iso}"``. They are opaque URL-safe strings — no
slashes, so the detail route uses a plain string converter.

Mirrors the equipment / work-orders / timecards / jobs / fleet_pnl /
vendors / cost_coding module pattern: two lightweight dependencies
(``get_engine`` and ``get_tenant_id``) so tests can override them via
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
from app.modules.bids import insights as insights_pipeline
from app.modules.bids import service
from app.modules.bids.schema import (
    BidDetail,
    BidListResponse,
    BidOutcome,
    BidsInsights,
    BidsSummary,
    CompetitionTier,
    MarginTier,
)

log = logging.getLogger("fieldbridge.bids")

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


@router.get("/summary", response_model=BidsSummary)
def summary(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
) -> BidsSummary:
    """KPI tiles — total bids, win-rate, VanCon bid dollars, pipeline."""
    return service.get_summary(engine, tenant_id)


@router.get("/list", response_model=BidListResponse)
def list_(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
    sort_by: Literal[
        "bid_date",
        "job",
        "vancon",
        "low",
        "rank",
        "number_bidders",
        "percent_over",
        "lost_by",
    ] = "bid_date",
    sort_dir: Literal["asc", "desc"] = "desc",
    outcome: BidOutcome | None = Query(
        None, description="Filter by outcome (won/lost/no_bid/unknown).",
    ),
    margin_tier: MarginTier | None = Query(
        None, description="Filter by margin tier vs. low bid.",
    ),
    competition_tier: CompetitionTier | None = Query(
        None, description="Filter by bidder-density tier.",
    ),
    bid_type: str | None = Query(
        None, description="Exact match on bid_type.", max_length=100,
    ),
    estimator: str | None = Query(
        None, description="Exact match on estimator.", max_length=100,
    ),
    county: str | None = Query(
        None, description="Exact match on county.", max_length=100,
    ),
    search: str | None = Query(
        None,
        description=(
            "Case-insensitive substring match on job / owner / "
            "estimator / county."
        ),
    ),
    close_max: float = Query(
        service.DEFAULT_CLOSE_MARGIN_MAX,
        ge=0.0, le=1.0,
        description=(
            "Upper bound on ``percent_over`` for the ``close`` margin "
            "tier. Default 0.03 (3%)."
        ),
    ),
    moderate_max: float = Query(
        service.DEFAULT_MODERATE_MARGIN_MAX,
        ge=0.0, le=1.0,
        description=(
            "Upper bound on ``percent_over`` for the ``moderate`` "
            "margin tier. Default 0.10 (10%)."
        ),
    ),
    light_max: int = Query(
        service.DEFAULT_LIGHT_BIDDERS_MAX,
        ge=2,
        description=(
            "Upper bound on ``number_bidders`` for the ``light`` "
            "competition tier."
        ),
    ),
    typical_max: int = Query(
        service.DEFAULT_TYPICAL_BIDDERS_MAX,
        ge=2,
        description=(
            "Upper bound on ``number_bidders`` for the ``typical`` "
            "competition tier."
        ),
    ),
) -> BidListResponse:
    """Paginated bids table with filters, sort, and tier tunables."""
    return service.list_bids(
        engine, tenant_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        outcome=outcome,
        margin_tier=margin_tier,
        competition_tier=competition_tier,
        bid_type=bid_type,
        estimator=estimator,
        county=county,
        search=search,
        close_max=close_max,
        moderate_max=moderate_max,
        light_max=light_max,
        typical_max=typical_max,
    )


@router.get("/insights", response_model=BidsInsights)
def insights(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    top_n: int = Query(
        service.DEFAULT_TOP_N, ge=1, le=100,
        description="How many rows to return in each top-N list.",
    ),
    close_max: float = Query(
        service.DEFAULT_CLOSE_MARGIN_MAX, ge=0.0, le=1.0,
    ),
    moderate_max: float = Query(
        service.DEFAULT_MODERATE_MARGIN_MAX, ge=0.0, le=1.0,
    ),
    light_max: int = Query(
        service.DEFAULT_LIGHT_BIDDERS_MAX, ge=2,
    ),
    typical_max: int = Query(
        service.DEFAULT_TYPICAL_BIDDERS_MAX, ge=2,
    ),
) -> BidsInsights:
    """Precomputed analytics: outcome / margin / competition breakdowns."""
    return service.get_insights(
        engine, tenant_id,
        top_n=top_n,
        close_max=close_max,
        moderate_max=moderate_max,
        light_max=light_max,
        typical_max=typical_max,
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
    """Phase-6 LLM-generated bid-strategy recommendations.

    Cached for ``DEFAULT_TTL_HOURS`` (6h) per ``(tenant, module)``;
    re-runs automatically when the underlying bids context changes
    (revision-token mismatch).
    """
    return insights_pipeline.build_recommendations(
        engine, tenant_id, force_refresh=refresh,
    )


# NOTE: ``/{bid_id}`` is declared LAST so the literal routes above
# (``/summary``, ``/list``, ``/insights``, ``/recommendations``) aren't
# shadowed by the dynamic converter.
@router.get("/{bid_id}", response_model=BidDetail)
def detail(
    bid_id: str,
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    close_max: float = Query(
        service.DEFAULT_CLOSE_MARGIN_MAX, ge=0.0, le=1.0,
    ),
    moderate_max: float = Query(
        service.DEFAULT_MODERATE_MARGIN_MAX, ge=0.0, le=1.0,
    ),
    light_max: int = Query(
        service.DEFAULT_LIGHT_BIDDERS_MAX, ge=2,
    ),
    typical_max: int = Query(
        service.DEFAULT_TYPICAL_BIDDERS_MAX, ge=2,
    ),
) -> BidDetail:
    """Detail view for a single bid (by synthetic 12-hex-char ID)."""
    result = service.get_bid_detail(
        engine, tenant_id, bid_id,
        close_max=close_max,
        moderate_max=moderate_max,
        light_max=light_max,
        typical_max=typical_max,
    )
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown bid id: {bid_id!r}"
        )
    return result
