"""Pydantic response models for the executive_dashboard module.

The dashboard is a *cross-module* rollup — it doesn't own any marts of
its own; it aggregates the same tables the per-module screens read.
That keeps the numbers on this page identical to what an exec would
see if they drilled into Jobs, Equipment, Bids, etc. independently.

Three response surfaces:

  * ``ExecutiveSummary`` — four KPI blocks (financial / ops / pipeline /
    roster) for the tile grid at the top of the page.
  * ``ExecutiveAttention`` — short, ranked lists of "things that need
    a CFO/owner's eyes today" (loss-making jobs, late jobs, big
    over/under-billing positions). The Recommendations rail will
    eventually wrap this with Claude-generated next actions.
  * ``ExecutiveTrend`` (lightweight) — the last 12 months of monthly
    revenue earned, sourced from ``mart_estimate_variance.close_month``,
    so the dashboard can render a sparkline without a separate API hit.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums                                                                       #
# --------------------------------------------------------------------------- #


class AttentionKind(str, Enum):
    """Why a job is flagged on the executive attention list.

    Mirrors the per-status enums used by the jobs module
    (``FinancialStatus``, ``ScheduleStatus``, ``BillingStatus``) but
    flattened into one rank-able stream.
    """

    LOSS = "loss"                     # est_gross_profit_pct < -2%
    LATE = "late"                     # proj_end past + < 100% complete
    AT_RISK = "at_risk"               # proj_end within 30 days
    OVER_BILLED = "over_billed"       # over_under_billings > +2% of contract
    UNDER_BILLED = "under_billed"     # over_under_billings < -2% of contract


# --------------------------------------------------------------------------- #
# Summary blocks                                                              #
# --------------------------------------------------------------------------- #


class FinancialPulse(BaseModel):
    """Aggregate of mart_job_wip across the active portfolio."""

    active_jobs: int = Field(
        ..., description="Number of WIP rows (active contracts).",
    )
    total_contract_value: float = Field(
        ..., description="SUM(total_contract) — total awarded backlog.",
    )
    total_revenue_earned: float = Field(
        ..., description="SUM(contract_revenues_earned) — earned to date.",
    )
    total_cost_to_date: float = Field(
        ..., description="SUM(contract_cost_td) — cost to date.",
    )
    total_estimated_gross_profit: float = Field(
        ..., description="SUM(est_gross_profit) — projected GP at completion.",
    )
    weighted_gross_profit_pct: float = Field(
        ...,
        description=(
            "Contract-weighted estimated GP %. Computed as "
            "SUM(est_gross_profit) / SUM(total_contract). Fractional "
            "(0.115 = 11.5%). 0.0 when no contracts on file."
        ),
    )
    total_over_under_billings: float = Field(
        ...,
        description=(
            "SUM(over_under_billings). Positive = net over-billed (cash "
            "ahead of revenue earned). Negative = net under-billed."
        ),
    )
    over_billed_jobs: int = 0
    under_billed_jobs: int = 0
    balanced_jobs: int = 0


class OperationsPulse(BaseModel):
    """Schedule + equipment activity rollup."""

    scheduled_jobs: int = Field(
        ..., description="Distinct jobs on mart_job_schedule.",
    )
    jobs_at_risk: int = Field(
        ..., description="proj_end within 30 days, < 100% complete.",
    )
    jobs_late: int = Field(
        ..., description="proj_end already past, < 100% complete.",
    )
    total_equipment: int = Field(
        ..., description="Distinct trucks ever seen on a utilization ticket.",
    )
    equipment_tickets_30d: int = Field(
        ..., description="COUNT(mart_equipment_utilization) last 30 days.",
    )
    equipment_revenue_30d: float = Field(
        ..., description="SUM(extended_price) last 30 days.",
    )


class PipelinePulse(BaseModel):
    """Bid outlook + history + proposal pipeline."""

    bids_in_pipeline: int = Field(
        ..., description="Rows in mart_bids_outlook (un-bid yet).",
    )
    bids_ready_for_review: int = Field(
        ..., description="ready_for_review = TRUE in mart_bids_outlook.",
    )
    upcoming_bids_30d: int = Field(
        ...,
        description=(
            "bid_date OR anticipated_bid_date falls within the next 30 days."
        ),
    )
    bids_submitted_ytd: int = Field(
        ..., description="mart_bids_history rows with bid_date YTD.",
    )
    bids_won_ytd: int = Field(
        ..., description="bids_submitted_ytd & won > 0.",
    )
    win_rate_ytd: float = Field(
        ...,
        description=(
            "bids_won_ytd / bids_submitted_ytd. Fractional (0.42 = 42%). "
            "0.0 when no bids submitted YTD."
        ),
    )
    proposals_outstanding: int = Field(
        ..., description="Rows in mart_proposals.",
    )


class RosterPulse(BaseModel):
    """Vendor + asset master counts."""

    total_vendors: int
    total_assets: int = Field(
        ..., description="Distinct barcodes in mart_asset_barcodes.",
    )
    retired_assets: int = Field(
        ..., description="retired_date IS NOT NULL in mart_asset_barcodes.",
    )


class ExecutiveSummary(BaseModel):
    """The full top-of-page tile blob.

    One round-trip; the four nested blocks render as four sections of
    the dashboard. Bag-of-counts on purpose so the frontend is just
    typography + sparklines.
    """

    as_of: datetime
    financial: FinancialPulse
    operations: OperationsPulse
    pipeline: PipelinePulse
    roster: RosterPulse


# --------------------------------------------------------------------------- #
# Attention list                                                              #
# --------------------------------------------------------------------------- #


class AttentionItem(BaseModel):
    """One row on the 'needs attention' rail.

    Deliberately shallow: enough for the card UI, no per-job blow-out.
    The frontend deep-links to ``/jobs/{job_id}`` for the full record.
    """

    job_id: str = Field(..., description="Stripped job description.")
    job: str = Field(..., description="Display label for the job.")
    kind: AttentionKind = Field(
        ..., description="What pulled this row onto the list.",
    )
    severity: float = Field(
        ...,
        description=(
            "Single-number rank for the UI. Larger = worse. Units depend "
            "on ``kind`` — dollars for billing items, percentage points "
            "for margin items, days for schedule items. The frontend "
            "treats it as opaque sort fuel."
        ),
    )
    detail: str = Field(
        ...,
        description=(
            "Human-readable summary, e.g. "
            "'$1.2M over-billed (8.3% of contract)' or "
            "'42 days past projected end'."
        ),
    )
    # Optional context fields the UI may use to render badges. Each is
    # nullable because the source mart may not have them on file.
    total_contract: float | None = None
    est_gross_profit_pct: float | None = None
    over_under_billings: float | None = None
    days_to_proj_end: int | None = None


class ExecutiveAttention(BaseModel):
    as_of: datetime
    items: list[AttentionItem]


# --------------------------------------------------------------------------- #
# Trend                                                                        #
# --------------------------------------------------------------------------- #


class MonthlyRevenuePoint(BaseModel):
    """One month on the revenue sparkline."""

    month: str = Field(..., description="ISO 'YYYY-MM' month label.")
    actual: float = Field(..., description="SUM(actual) for that close_month.")
    estimate: float = Field(..., description="SUM(estimate) for that close_month.")


class ExecutiveTrend(BaseModel):
    as_of: datetime
    months: list[MonthlyRevenuePoint] = Field(
        ...,
        description=(
            "Trailing N months ordered ascending (oldest first), so the "
            "frontend can render a left-to-right sparkline directly."
        ),
    )
