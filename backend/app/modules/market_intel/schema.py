"""Pydantic response models for the Market Intel module.

Mirrored exactly by ``frontend/src/modules/market-intel/api/types.ts``.
Any change here must have a matching change there — see the worker
brief at ``frontend/src/modules/market-intel/PROPOSED_CHANGES.md``.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class CompetitorCurveRow(BaseModel):
    """One competitor's pricing personality across the network.

    ``median_rank`` of 1 = always the low bidder; higher = consistently
    further from low. ``avg_premium_over_low`` is decimal: 0.05 = 5%
    above the winning bid.
    """

    contractor_name: str
    bid_count: int
    avg_premium_over_low: float = Field(
        ...,
        description="Decimal premium over low; 0.05 = 5% above winner",
    )
    median_rank: float
    win_rate: float = Field(..., ge=0.0, le=1.0)


class OpportunityRow(BaseModel):
    """One county-or-state cell where similar-scope work happened
    but VanCon never bid."""

    state: str = Field(..., min_length=2, max_length=2)
    county: str | None = None
    missed_count: int
    avg_low_bid: float
    top_scope_codes: list[str]


class CalibrationPoint(BaseModel):
    """One quarter of VanCon's own bid calibration."""

    quarter: date
    bids_submitted: int
    wins: int
    avg_rank: float
    pct_above_low: float | None = None
