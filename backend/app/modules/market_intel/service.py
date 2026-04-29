"""Query layer for Market Intel reads.

All three analytics endpoints share a tenant-scoping pattern:
``WHERE tenant_id IN (:caller_tenant, :shared_network_tenant)``.
The shared-network sentinel ID is loaded from ``app.core.seed``.

This module is a STUB at v1.5 scaffold. Implementation lands when the
Market Intel Backend Worker fills in the SQL — until then every query
returns an empty list. Routes return 200 with empty payloads (NOT 501)
so the frontend can light up against real endpoints with empty data,
matching the production state during dark accumulation.
"""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_intel.schema import (
    CalibrationPoint,
    CompetitorCurveRow,
    OpportunityRow,
)

log = logging.getLogger("fieldbridge.market_intel")


async def get_competitor_curves(
    db: AsyncSession,
    *,
    states: list[str],
    months_back: int,
    min_bids: int,
    tenant_id: str,
) -> list[CompetitorCurveRow]:
    """Return per-competitor pricing curves for the caller's tenant union
    the shared-network dataset. STUB — returns []."""
    log.info(
        "competitor_curves stub: states=%s months_back=%d min_bids=%d",
        states, months_back, min_bids,
    )
    return []


async def get_opportunity_gaps(
    db: AsyncSession,
    *,
    bid_min: int,
    bid_max: int,
    months_back: int,
    tenant_id: str,
) -> list[OpportunityRow]:
    """Return county-level gaps where similar-scope work happens but the
    caller never bids. STUB — returns []."""
    log.info(
        "opportunity_gaps stub: bid_min=%d bid_max=%d months_back=%d",
        bid_min, bid_max, months_back,
    )
    return []


async def get_bid_calibration(
    db: AsyncSession,
    *,
    contractor_name_match: str,
    tenant_id: str,
) -> list[CalibrationPoint]:
    """Return per-quarter calibration of a contractor's bids vs the low
    bidder. STUB — returns []."""
    log.info(
        "bid_calibration stub: contractor_name_match=%r",
        contractor_name_match,
    )
    return []
