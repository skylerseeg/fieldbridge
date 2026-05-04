"""FastAPI router for the proposals module.

Endpoints (mounted at ``/api/proposals`` in ``app.main``):
    GET /summary             KPI tiles.
    GET /list                Paginated, filterable, sortable table.
    GET /insights            Precomputed analytics.
    GET /{proposal_id}       Detail row for a single proposal.

Proposal IDs are synthetic: a 12-hex-char MD5 prefix of
``f"{job}|{owner}|{bid_type}"``. Opaque URL-safe strings — no
slashes, so the detail route uses a plain string converter.

Mirrors the equipment / work-orders / timecards / jobs / fleet_pnl /
vendors / cost_coding / bids module pattern: two lightweight
dependencies (``get_engine`` and ``get_tenant_id``) so tests can
override them via ``app.dependency_overrides``.
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
from app.modules.proposals import insights as insights_pipeline
from app.modules.proposals import service
from app.modules.proposals.schema import (
    BidTypeCategory,
    GeographyTier,
    ProposalDetail,
    ProposalListResponse,
    ProposalsInsights,
    ProposalsSummary,
)

log = logging.getLogger("fieldbridge.proposals")

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



# --------------------------------------------------------------------------- #
# Endpoints                                                                   #
# --------------------------------------------------------------------------- #


@router.get("/summary", response_model=ProposalsSummary)
def summary(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    primary_state: str = Query(
        service.DEFAULT_PRIMARY_STATE,
        min_length=2, max_length=2,
        description=(
            "Two-letter state code treated as in-state. Default ``UT``."
        ),
    ),
) -> ProposalsSummary:
    """KPI tiles — proposal counts, geography mix, line-item totals."""
    return service.get_summary(engine, tenant_id, primary_state=primary_state)


@router.get("/list", response_model=ProposalListResponse)
def list_(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
    sort_by: Literal["job", "owner", "bid_type", "county"] = "job",
    sort_dir: Literal["asc", "desc"] = "asc",
    bid_type_category: BidTypeCategory | None = Query(
        None, description="Filter by derived bid-type category.",
    ),
    geography_tier: GeographyTier | None = Query(
        None, description="Filter by in-state / out-of-state / unknown.",
    ),
    bid_type: str | None = Query(
        None, description="Exact match on bid_type.", max_length=200,
    ),
    owner: str | None = Query(
        None, description="Exact match on owner.", max_length=200,
    ),
    county: str | None = Query(
        None, description="Exact match on county.", max_length=200,
    ),
    state_code: str | None = Query(
        None,
        description=(
            "Filter by parsed two-letter state code (case-insensitive)."
        ),
        min_length=2, max_length=2,
    ),
    search: str | None = Query(
        None,
        description=(
            "Case-insensitive substring match on job / owner / "
            "bid_type / county."
        ),
    ),
    primary_state: str = Query(
        service.DEFAULT_PRIMARY_STATE,
        min_length=2, max_length=2,
        description=(
            "Two-letter state code for the in-state / out-of-state "
            "classifier. Default ``UT``."
        ),
    ),
) -> ProposalListResponse:
    """Paginated proposals table with filters, sort, and state tunable."""
    return service.list_proposals(
        engine, tenant_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        bid_type_category=bid_type_category,
        geography_tier=geography_tier,
        bid_type=bid_type,
        owner=owner,
        county=county,
        state_code=state_code,
        search=search,
        primary_state=primary_state,
    )


@router.get("/insights", response_model=ProposalsInsights)
def insights(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    top_n: int = Query(
        service.DEFAULT_TOP_N, ge=1, le=100,
        description="How many rows to return in each top-N list.",
    ),
    primary_state: str = Query(
        service.DEFAULT_PRIMARY_STATE,
        min_length=2, max_length=2,
    ),
) -> ProposalsInsights:
    """Precomputed analytics: bid-type / geography mix, top segments, line-item stats."""
    return service.get_insights(
        engine, tenant_id,
        top_n=top_n,
        primary_state=primary_state,
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
    """Phase-6 LLM-generated proposal-strategy recommendations.

    Cached for ``DEFAULT_TTL_HOURS`` (6h) per ``(tenant, module)``;
    re-runs automatically when the underlying proposals context changes
    (revision-token mismatch).
    """
    return insights_pipeline.build_recommendations(
        engine, tenant_id, force_refresh=refresh,
    )


# NOTE: ``/{proposal_id}`` is declared LAST so the literal routes above
# (``/summary``, ``/list``, ``/insights``, ``/recommendations``) aren't
# shadowed by the dynamic converter.
@router.get("/{proposal_id}", response_model=ProposalDetail)
def detail(
    proposal_id: str,
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    primary_state: str = Query(
        service.DEFAULT_PRIMARY_STATE,
        min_length=2, max_length=2,
    ),
) -> ProposalDetail:
    """Detail view for a single proposal (by synthetic 12-hex-char ID)."""
    result = service.get_proposal_detail(
        engine, tenant_id, proposal_id, primary_state=primary_state,
    )
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown proposal id: {proposal_id!r}"
        )
    return result
