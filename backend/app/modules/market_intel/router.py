"""FastAPI router for Market Intel.

Read endpoints (mounted at ``/api/market-intel`` in ``app.main``):
    GET  /competitor-curves
    GET  /opportunity-gaps
    GET  /bid-calibration

Admin endpoint (gated by ``require_admin`` — fieldbridge_admin role):
    POST /admin/run-itd-pipeline    invoked nightly by n8n cron

All read endpoints are tenant-scoped: the caller's tenant_id comes
from ``get_current_tenant`` (JWT-derived); queries union it with the
shared-network sentinel so the cross-tenant ITD dataset is visible.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_tenant, require_admin
from app.core.database import get_db
from app.models.tenant import Tenant
from app.modules.market_intel import service
from app.modules.market_intel.schema import (
    CalibrationPoint,
    CompetitorCurveRow,
    ITDPipelineRunResponse,
    OpportunityRow,
)
from app.services.market_intel.pipeline import ITDPipeline

router = APIRouter()
log = logging.getLogger("fieldbridge.market_intel.router")


@router.get(
    "/competitor-curves",
    response_model=list[CompetitorCurveRow],
    summary="Per-competitor pricing curve",
)
async def competitor_curves(
    states: Annotated[
        list[str],
        Query(
            description="Two-letter state codes; defaults to VanCon's region",
        ),
    ] = ["UT", "ID", "NV", "WY", "CO", "AZ"],
    months_back: Annotated[int, Query(ge=1, le=120)] = 36,
    min_bids: Annotated[int, Query(ge=1)] = 10,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
) -> list[CompetitorCurveRow]:
    """Median rank × premium-over-low for every competitor with
    ``min_bids`` or more public bids in the requested window."""
    return await service.get_competitor_curves(
        db,
        states=states,
        months_back=months_back,
        min_bids=min_bids,
        tenant_id=tenant.id,
    )


@router.get(
    "/opportunity-gaps",
    response_model=list[OpportunityRow],
    summary="Counties where similar-scope work happens but the caller never bids",
)
async def opportunity_gaps(
    bid_min: Annotated[int, Query(ge=0)] = 250_000,
    bid_max: Annotated[int, Query(ge=0)] = 5_000_000,
    months_back: Annotated[int, Query(ge=1, le=60)] = 24,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
) -> list[OpportunityRow]:
    """Geographies where similar-scope public work is happening but
    the caller's tenant never showed up on the bidder list."""
    return await service.get_opportunity_gaps(
        db,
        bid_min=bid_min,
        bid_max=bid_max,
        months_back=months_back,
        tenant_id=tenant.id,
    )


@router.get(
    "/bid-calibration",
    response_model=list[CalibrationPoint],
    summary="Caller's own bid calibration over time",
)
async def bid_calibration(
    contractor_name_match: Annotated[
        str,
        Query(min_length=2, description="ILIKE match for caller in bid_results"),
    ] = "van con",
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
) -> list[CalibrationPoint]:
    """Per-quarter trend: bids submitted, wins, avg rank, pct above low."""
    return await service.get_bid_calibration(
        db,
        contractor_name_match=contractor_name_match,
        tenant_id=tenant.id,
    )


# ---------------------------------------------------------------------------
# Admin: ingest trigger (n8n cron-driven)

@router.post(
    "/admin/run-itd-pipeline",
    response_model=ITDPipelineRunResponse,
    summary="Run the ITD ingest pipeline once (admin-only, n8n cron)",
)
async def run_itd_pipeline_endpoint(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin()),
) -> ITDPipelineRunResponse:
    """Execute one ``ITDPipeline.run_state("ID", db)`` against the
    request's DB session and return the counters dict.

    Invoked by ``workers/n8n_flows/market_intel_daily.json`` once
    per night. Idempotent — re-running on the same data writes zero
    new rows (see ``skipped_already_ingested``). Hard failures
    (5xx upstream, robots-deny on the index page, network) return
    a counters dict with zeros, not an HTTP error — n8n's logging
    + alerting branch on the dict, not on the HTTP status.
    """
    log.info("admin: starting ITD pipeline run for state=ID")
    async with ITDPipeline() as pipeline:
        counters = await pipeline.run_state("ID", db)
    log.info("admin: ITD pipeline run complete %s", counters)
    return ITDPipelineRunResponse(**counters)
