"""Pydantic response models for the jobs module.

Primary entity: an active contract/job, keyed by its stripped
description (leading whitespace removed — Vista's `jcjm.Description`
often has leading spaces that would break URL routing otherwise).

Three statuses cover the screens a PM would check each morning:
  - ``ScheduleStatus``: is this job on-track to hit its projected end?
  - ``FinancialStatus``: is estimated gross profit positive / breakeven / a loss?
  - ``BillingStatus``: is billing leading, lagging, or tracking cost?
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums                                                                       #
# --------------------------------------------------------------------------- #


class ScheduleStatus(str, Enum):
    """Where a job stands against its projected end date.

    ``at_risk`` = proj_end falls within ``at_risk_days`` of today.
    ``late`` = proj_end is already in the past and the job isn't fully
    complete (percent_complete < 100%).
    """

    ON_SCHEDULE = "on_schedule"
    AT_RISK = "at_risk"
    LATE = "late"
    NO_SCHEDULE = "no_schedule"   # no proj_end on file
    UNKNOWN = "unknown"            # job not in mart_job_schedule


class FinancialStatus(str, Enum):
    """Margin bucket. Threshold band makes near-zero a real state."""

    PROFITABLE = "profitable"   # est_gross_profit_pct > +breakeven_band
    BREAKEVEN = "breakeven"     # |pct| <= breakeven_band
    LOSS = "loss"               # pct < -breakeven_band
    UNKNOWN = "unknown"         # no margin on file


class BillingStatus(str, Enum):
    """Over/under-billing vs contract.

    Over-billing (positive over_under_billings) means we've billed more
    than we've earned — a cash-flow positive but margin risk.
    """

    OVER_BILLED = "over_billed"
    BALANCED = "balanced"
    UNDER_BILLED = "under_billed"
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------- #
# List / detail                                                               #
# --------------------------------------------------------------------------- #


class JobListRow(BaseModel):
    id: str = Field(
        ...,
        description=(
            "Stripped job description (e.g. '2231. UDOT Bangerter Hwy'). "
            "Used in the ``/{job_id}`` detail URL."
        ),
    )
    job: str = Field(..., description="Canonical job description (stripped).")

    # --- schedule side ---
    priority: int | None = Field(
        None, description="Rank from mart_job_schedule. None if not scheduled.",
    )
    start: datetime | None = None
    proj_end: datetime | None = None
    milestone: datetime | None = None
    schedule_days_to_end: int | None = Field(
        None,
        description=(
            "Days from today to proj_end. Negative = past projected end. "
            "None when proj_end is missing."
        ),
    )
    schedule_status: ScheduleStatus = ScheduleStatus.UNKNOWN

    # --- financial side ---
    total_contract: float | None = None
    contract_cost_td: float | None = None
    est_total_cost: float | None = None
    est_gross_profit: float | None = None
    est_gross_profit_pct: float | None = Field(
        None, description="Estimated gross profit ratio (0.20 = 20%).",
    )
    gross_profit_pct_td: float | None = Field(
        None, description="Realized gross profit ratio to date.",
    )
    percent_complete: float | None = Field(
        None, description="0.0–1.0 (or >1.0 if overrun).",
    )
    billings_to_date: float | None = None
    over_under_billings: float | None = Field(
        None,
        description=(
            "Positive = over-billed (billed > earned). "
            "Negative = under-billed (earned > billed)."
        ),
    )

    financial_status: FinancialStatus = FinancialStatus.UNKNOWN
    billing_status: BillingStatus = BillingStatus.UNKNOWN


class JobListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    sort_by: str
    sort_dir: Literal["asc", "desc"]
    items: list[JobListRow]


class EstimateHistoryPoint(BaseModel):
    """Historical estimate vs actual for one close month."""

    close_month: datetime
    estimate: float | None = None
    actual: float | None = None
    variance: float | None = None
    variance_pct: float | None = Field(
        None,
        description=(
            "variance / estimate * 100 (positive = under-estimated). "
            "None when estimate is 0 or missing."
        ),
    )


class JobDetail(BaseModel):
    """Single-job detail — list fields plus full estimate history."""

    id: str
    job: str

    priority: int | None = None
    start: datetime | None = None
    proj_end: datetime | None = None
    milestone: datetime | None = None
    schedule_days_to_end: int | None = None
    schedule_status: ScheduleStatus = ScheduleStatus.UNKNOWN
    reason: str | None = Field(
        None, description="Narrative from mart_job_schedule.",
    )

    total_contract: float | None = None
    contract_cost_td: float | None = None
    est_cost_to_complete: float | None = None
    est_total_cost: float | None = None
    est_gross_profit: float | None = None
    est_gross_profit_pct: float | None = None
    percent_complete: float | None = None
    gain_fade_from_prior_mth: float | None = None
    billings_to_date: float | None = None
    over_under_billings: float | None = None
    contract_revenues_earned: float | None = None
    gross_profit_loss_td: float | None = None
    gross_profit_pct_td: float | None = None

    financial_status: FinancialStatus = FinancialStatus.UNKNOWN
    billing_status: BillingStatus = BillingStatus.UNKNOWN

    estimate_history: list[EstimateHistoryPoint] = Field(
        default_factory=list,
        description=(
            "Per-close-month estimate vs actual rows from "
            "mart_estimate_variance, ordered chronologically."
        ),
    )


# --------------------------------------------------------------------------- #
# Summary (KPI tiles)                                                         #
# --------------------------------------------------------------------------- #


class JobSummary(BaseModel):
    """KPI tiles at the top of the Jobs screen."""

    total_jobs: int = Field(
        ..., description="Union of WIP + schedule — every tracked job.",
    )
    jobs_with_wip: int = Field(
        ..., description="Jobs that have a WIP row (financial data).",
    )
    jobs_scheduled: int = Field(
        ..., description="Jobs that have a schedule row (dated).",
    )

    total_contract_value: float = Field(
        ..., description="Sum of total_contract across WIP rows.",
    )
    total_cost_to_date: float = Field(
        ..., description="Sum of contract_cost_td across WIP rows.",
    )
    total_revenue_earned: float = Field(
        ..., description="Sum of contract_revenues_earned across WIP rows.",
    )
    total_gross_profit_td: float = Field(
        ..., description="Sum of gross_profit_loss_td across WIP rows.",
    )

    weighted_avg_margin_pct: float | None = Field(
        None,
        description=(
            "(total_gross_profit_td / total_revenue_earned) * 100. "
            "None when no revenue earned."
        ),
    )
    avg_percent_complete: float = Field(
        ...,
        description=(
            "Mean of percent_complete across WIP rows (fractional — 0.0–1.0)."
        ),
    )

    # Schedule buckets
    jobs_on_schedule: int
    jobs_at_risk: int
    jobs_late: int

    # Financial buckets
    jobs_profitable: int
    jobs_breakeven: int
    jobs_loss: int

    # Billing buckets
    jobs_over_billed: int
    jobs_under_billed: int
    jobs_balanced: int


# --------------------------------------------------------------------------- #
# Insights                                                                    #
# --------------------------------------------------------------------------- #


class ScheduleBreakdown(BaseModel):
    on_schedule: int
    at_risk: int
    late: int
    no_schedule: int
    unknown: int


class FinancialBreakdown(BaseModel):
    profitable: int
    breakeven: int
    loss: int
    unknown: int


class BillingMetrics(BaseModel):
    over_billed_count: int
    balanced_count: int
    under_billed_count: int
    unknown_count: int
    total_over_billed: float = Field(
        ..., description="Sum of positive over_under_billings values.",
    )
    total_under_billed: float = Field(
        ...,
        description=(
            "Sum of negative over_under_billings values expressed as "
            "a positive magnitude."
        ),
    )


class EstimateAccuracy(BaseModel):
    """Aggregate estimating accuracy from mart_estimate_variance."""

    samples: int = Field(
        ..., description="Rows contributing to these aggregates.",
    )
    jobs_tracked: int = Field(
        ...,
        description="Distinct jobs with at least one variance row.",
    )
    avg_variance_pct: float | None = Field(
        None,
        description=(
            "Arithmetic mean of per-row variance percent. Positive = "
            "actuals ran under estimate (money left over)."
        ),
    )
    avg_abs_variance_pct: float | None = Field(
        None,
        description=(
            "Mean of |variance_pct| — how far off estimates are, ignoring "
            "sign. Closer to 0 is better."
        ),
    )


class JobMoneyRow(BaseModel):
    """One row for the top-profit / top-loss / top-billing lists."""

    id: str
    job: str
    value: float = Field(
        ...,
        description=(
            "The amount that got this row into the list (gross profit $, "
            "loss $, over_under_billings $, etc.)."
        ),
    )
    percent_complete: float | None = None
    total_contract: float | None = None


class JobsInsights(BaseModel):
    as_of: datetime
    at_risk_days: int = Field(
        ...,
        description=(
            "Days-until-proj_end window that classifies a job as at_risk. "
            "Default 30."
        ),
    )
    breakeven_band_pct: float = Field(
        ...,
        description=(
            "± margin-percent band around 0 that is classified as "
            "breakeven. Default 2.0 (percentage points of margin)."
        ),
    )
    billing_balance_pct: float = Field(
        ...,
        description=(
            "|over_under_billings| / total_contract tolerance for "
            "``balanced`` (percent). Default 2.0."
        ),
    )

    schedule_breakdown: ScheduleBreakdown
    financial_breakdown: FinancialBreakdown
    billing_metrics: BillingMetrics
    estimate_accuracy: EstimateAccuracy

    top_profit: list[JobMoneyRow] = Field(
        default_factory=list,
        description="Top-N jobs by estimated gross profit $.",
    )
    top_loss: list[JobMoneyRow] = Field(
        default_factory=list,
        description=(
            "Top-N jobs by gross loss (most negative est_gross_profit $)."
        ),
    )
    top_over_billed: list[JobMoneyRow] = Field(
        default_factory=list,
        description="Top-N jobs by over_under_billings (positive).",
    )
    top_under_billed: list[JobMoneyRow] = Field(
        default_factory=list,
        description=(
            "Top-N jobs by under-billing magnitude (most-negative first)."
        ),
    )
