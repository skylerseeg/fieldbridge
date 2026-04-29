"""FastAPI router for Market Intel reads.

Endpoints (mounted at ``/api/market-intel`` in ``app.main``):
    GET /competitor-curves
    GET /opportunity-gaps
    GET /bid-calibration

All three are tenant-scoped reads. The caller's tenant_id comes from
``get_current_tenant`` (JWT-derived); queries union it with the
shared-network sentinel so the cross-tenant NAPC dataset is visible.

Implementation is a STUB at v1.5 scaffold — routes return 200 with []
until the Backend Worker fills in the SQL templates in
``app/services/market_intel/analytics/``.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_tenant
from app.core.database import get_db
from app.models.tenant import Tenant
from app.modules.market_intel import service
from app.modules.market_intel.schema import (
    CalibrationPoint,
    CompetitorCurveRow,
    OpportunityRow,
)

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
