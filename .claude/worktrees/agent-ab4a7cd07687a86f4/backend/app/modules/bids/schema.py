"""Pydantic response models for the bids module.

Primary entity: one **bid row** from ``mart_bids_history`` — a
(job, bid_date) pair capturing VanCon's submission (or decision not
to bid), the competitor bid range, and the outcome.

Three orthogonal classifications per bid:
  - ``BidOutcome``: won / lost / no_bid / unknown (from ``rank`` and
    ``was_bid``).
  - ``MarginTier``: how close VanCon came (``percent_over`` banding).
  - ``CompetitionTier``: how many bidders competed (``number_bidders``
    banding).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums                                                                       #
# --------------------------------------------------------------------------- #


class BidOutcome(str, Enum):
    """Did VanCon win this bid?

    Derived from ``was_bid`` and ``rank``:
      - ``WON``     : ``was_bid == 1`` and ``rank == 1``.
      - ``LOST``    : ``was_bid == 1`` and ``rank > 1``.
      - ``NO_BID``  : ``was_bid == 0`` (VanCon walked away).
      - ``UNKNOWN`` : ``was_bid == 1`` but ``rank`` is null.
    """

    WON = "won"
    LOST = "lost"
    NO_BID = "no_bid"
    UNKNOWN = "unknown"


class MarginTier(str, Enum):
    """How close VanCon came to winning.

    Bands on ``percent_over`` (VanCon / low - 1). ``WINNER`` if
    VanCon was the low bidder.
    """

    WINNER = "winner"        # rank == 1
    CLOSE = "close"          # percent_over <= close_max
    MODERATE = "moderate"    # <= moderate_max
    WIDE = "wide"            # > moderate_max
    UNKNOWN = "unknown"      # percent_over is null


class CompetitionTier(str, Enum):
    """Bidder density bucket."""

    SOLO = "solo"          # exactly 1 bidder
    LIGHT = "light"        # 2..light_max
    TYPICAL = "typical"    # light_max+1..typical_max
    CROWDED = "crowded"    # > typical_max
    UNKNOWN = "unknown"    # number_bidders null


# --------------------------------------------------------------------------- #
# List / detail                                                               #
# --------------------------------------------------------------------------- #


class BidListRow(BaseModel):
    id: str = Field(
        ...,
        description=(
            "Stable hash of ``job|bid_date`` (12-hex chars). Used in "
            "the ``/{bid_id}`` detail URL."
        ),
    )
    job: str
    bid_date: datetime

    was_bid: bool = Field(
        ..., description="Did VanCon actually submit a bid?",
    )
    owner: str | None = None
    bid_type: str | None = None
    county: str | None = None
    estimator: str | None = None

    vancon: float | None = Field(
        None, description="VanCon's bid amount (null if did not submit).",
    )
    low: float | None = None
    high: float | None = None
    engineer_estimate: str | None = Field(
        None,
        description="Engineer's estimate bucket (e.g. ``$1M to $2M``).",
    )

    rank: int | None = None
    number_bidders: int | None = None
    lost_by: float | None = Field(
        None,
        description="Dollars between VanCon's bid and the low bid.",
    )
    percent_over: float | None = Field(
        None,
        description=(
            "``vancon / low - 1`` expressed as a fraction. 0 when "
            "VanCon was the low bidder. None when ``low`` is null."
        ),
    )

    outcome: BidOutcome = BidOutcome.UNKNOWN
    margin_tier: MarginTier = MarginTier.UNKNOWN
    competition_tier: CompetitionTier = CompetitionTier.UNKNOWN


class BidListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    sort_by: str
    sort_dir: Literal["asc", "desc"]
    items: list[BidListRow]


class CompetitorBidSlot(BaseModel):
    """One of the wide bid_{i}_comp / bid_{i}_amt / bid_{i}_won slots."""

    slot: int = Field(
        ..., description="Original slot index (1..17) in the wide row.",
    )
    competitor: str | None = None
    amount: float | None = None
    won_amount: float | None = Field(
        None,
        description=(
            "Winning bid recorded in this slot (mart column "
            "``bid_{i}_won``). Often equal to the overall ``low``."
        ),
    )


class BidDetail(BaseModel):
    """Single bid detail — list fields plus markups, flags, competitors."""

    id: str
    job: str
    bid_date: datetime

    was_bid: bool
    owner: str | None = None
    bid_type: str | None = None
    county: str | None = None
    estimator: str | None = None

    vancon: float | None = None
    low: float | None = None
    high: float | None = None
    engineer_estimate: str | None = None

    rank: int | None = None
    number_bidders: int | None = None
    lost_by: float | None = None
    percent_over: float | None = None

    outcome: BidOutcome = BidOutcome.UNKNOWN
    margin_tier: MarginTier = MarginTier.UNKNOWN
    competition_tier: CompetitionTier = CompetitionTier.UNKNOWN

    # Markup / cost-factor diagnostics.
    labor_cost_factor: float | None = None
    avg_mark_up_pct: float | None = None
    mark_up: float | None = None
    overhead_add_on: float | None = None
    equip_op_exp: float | None = None
    co_equip: float | None = None

    completion_date: datetime | None = None
    notice_to_proceed_date: datetime | None = None

    pq: bool | None = None
    db_wages: bool | None = None
    plan_source: str | None = None

    risk_flags: list[str] = Field(
        default_factory=list,
        description=(
            "Risk-flag column names that were true for this bid "
            "(subset of deep / traffic_control / dewatering / "
            "bypass_pumping / tight_time_frame / tight_job_site / "
            "haul_off / insurance_requirement)."
        ),
    )

    competitors: list[CompetitorBidSlot] = Field(
        default_factory=list,
        description=(
            "Populated competitor slots from the wide bid_{i}_* "
            "columns, sorted by ``amount`` ascending (nulls last)."
        ),
    )


# --------------------------------------------------------------------------- #
# Summary (KPI tiles)                                                         #
# --------------------------------------------------------------------------- #


class BidsSummary(BaseModel):
    """KPI tiles at the top of the Bids screen."""

    total_bids: int = Field(
        ..., description="Total mart rows (submitted + walked)."
    )
    bids_submitted: int
    no_bids: int
    bids_won: int
    bids_lost: int
    unknown_outcome: int = Field(
        0,
        description=(
            "Bids VanCon submitted but ``rank`` is null — outcome "
            "hasn't been recorded."
        ),
    )

    win_rate: float = Field(
        0.0,
        description=(
            "``bids_won / bids_submitted``. 0 when no submissions."
        ),
    )

    total_vancon_bid_amount: float = Field(
        0.0,
        description="Sum of ``vancon`` across all submitted bids.",
    )
    total_vancon_won_amount: float = Field(
        0.0,
        description="Sum of ``vancon`` where VanCon won (rank == 1).",
    )
    avg_vancon_bid: float = Field(
        0.0,
        description="Average VanCon bid amount across submissions.",
    )
    median_number_bidders: float | None = Field(
        None,
        description=(
            "Median bidder count across submissions with known "
            "``number_bidders``. None if no such bids."
        ),
    )

    distinct_estimators: int
    distinct_owners: int
    distinct_counties: int
    distinct_bid_types: int

    outlook_count: int = Field(
        0,
        description=(
            "Rows in ``mart_bids_outlook`` for this tenant — "
            "pipeline of upcoming bids."
        ),
    )


# --------------------------------------------------------------------------- #
# Insights                                                                    #
# --------------------------------------------------------------------------- #


class OutcomeBreakdown(BaseModel):
    won: int = 0
    lost: int = 0
    no_bid: int = 0
    unknown: int = 0


class MarginTierBreakdown(BaseModel):
    winner: int = 0
    close: int = 0
    moderate: int = 0
    wide: int = 0
    unknown: int = 0


class CompetitionTierBreakdown(BaseModel):
    solo: int = 0
    light: int = 0
    typical: int = 0
    crowded: int = 0
    unknown: int = 0


class WinRateBySegmentRow(BaseModel):
    """Win-rate rollup for an estimator / bid_type / county segment."""

    segment: str
    submitted: int
    won: int
    lost: int
    unknown: int = 0
    win_rate: float = Field(
        0.0,
        description="``won / submitted``. 0 when submitted is 0.",
    )
    total_vancon_won_amount: float = 0.0


class NearMissRow(BaseModel):
    """A close loss — lost_by / percent_over minimized."""

    id: str
    job: str
    bid_date: datetime
    vancon: float | None = None
    low: float | None = None
    lost_by: float | None = None
    percent_over: float | None = None
    estimator: str | None = None


class BigWinRow(BaseModel):
    """A big win — top wins by VanCon's bid value."""

    id: str
    job: str
    bid_date: datetime
    vancon: float
    owner: str | None = None
    bid_type: str | None = None
    estimator: str | None = None


class RiskFlagFrequencyRow(BaseModel):
    flag: str
    count: int = Field(
        ..., description="Bids where this flag column is truthy (1.0)."
    )
    win_rate: float = Field(
        0.0,
        description=(
            "Win-rate among submitted bids carrying this flag. 0 "
            "when no flagged submissions."
        ),
    )


class BidsInsights(BaseModel):
    outcome_breakdown: OutcomeBreakdown
    margin_tier_breakdown: MarginTierBreakdown
    competition_tier_breakdown: CompetitionTierBreakdown

    win_rate_by_bid_type: list[WinRateBySegmentRow] = Field(
        default_factory=list,
        description="Top-N bid types ranked by submission count.",
    )
    win_rate_by_estimator: list[WinRateBySegmentRow] = Field(
        default_factory=list,
        description="Top-N estimators ranked by submission count.",
    )
    win_rate_by_county: list[WinRateBySegmentRow] = Field(
        default_factory=list,
        description="Top-N counties ranked by submission count.",
    )
    near_misses: list[NearMissRow] = Field(
        default_factory=list,
        description=(
            "Top-N closest losses by ``lost_by`` ascending — "
            "candidate pricing-strategy targets."
        ),
    )
    big_wins: list[BigWinRow] = Field(
        default_factory=list,
        description="Top-N wins by VanCon bid value (descending).",
    )
    risk_flag_frequency: list[RiskFlagFrequencyRow] = Field(
        default_factory=list,
        description=(
            "Per-flag counts and win-rate for the eight boolean "
            "risk-flag columns (deep, traffic_control, dewatering, "
            "bypass_pumping, tight_time_frame, tight_job_site, "
            "haul_off, insurance_requirement)."
        ),
    )
