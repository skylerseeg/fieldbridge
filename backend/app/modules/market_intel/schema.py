"""Pydantic response models for the Market Intel module.

Mirrored exactly by ``frontend/src/modules/market-intel/api/types.ts``.
Any change here must have a matching change there — see the worker
brief at ``frontend/src/modules/market-intel/PROPOSED_CHANGES.md``.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


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


class CountyGapEvent(BaseModel):
    """One bid event in an opportunity-gap county where the caller's
    contractor never appeared on the bidder list.

    Returned by ``GET /api/market-intel/gap/{state}/{county}`` — the
    drill-in view from the Opportunity gaps tab's top-N county list.
    """

    # Pydantic v2: serialize date as ISO-8601 string for the JSON wire
    # response so the React side gets a plain "YYYY-MM-DD" rather than
    # a Python-style date repr.
    model_config = ConfigDict(json_encoders={date: lambda d: d.isoformat()})

    bid_event_id: str
    project_title: str
    project_owner: str | None = None
    solicitation_id: str | None = None
    source_url: str
    source_state: str = Field(..., min_length=2, max_length=2)
    source_network: str
    bid_open_date: date
    location_state: str = Field(..., min_length=2, max_length=2)
    location_county: str | None = None
    csi_codes: list[str] = Field(default_factory=list)
    low_bidder_name: str
    low_bid_amount: float = Field(
        ...,
        ge=0.0,
        description="Winning low bid in USD",
    )


class ITDPipelineRunResponse(BaseModel):
    """Counters returned by ``POST /admin/run-itd-pipeline``.

    Mirrors the dict shape from ``ITDPipeline.run_state``. n8n's daily
    cron flow (``workers/n8n_flows/market_intel_daily.json``) reads
    these into its log line and alerts on non-zero
    ``skipped_parse_error`` / ``skipped_fetch_error`` (out-of-band
    indicators that something is going sideways at the source).
    """

    fetched: int
    parsed: int
    written: int
    skipped_robots: int
    skipped_fetch_error: int
    skipped_legacy_template: int
    skipped_parse_error: int
    skipped_already_ingested: int
    duration_ms: int
