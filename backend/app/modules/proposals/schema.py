"""Pydantic response models for the proposals module.

Primary entity: one **proposal header** from ``mart_proposals``,
keyed on ``(job, owner, bid_type)``. Each proposal gets two
derived classifications:

  - ``BidTypeCategory`` — keyword bucketing of the ``bid_type`` string
    (pressurized / structures / concrete / earthwork / other).
  - ``GeographyTier`` — derived from the two-letter state suffix in
    ``county`` vs. the tenant's primary state (``in_state`` /
    ``out_of_state`` / ``unknown``).

Line items live in a separate mart (``mart_proposal_line_items``) that
does not yet link back to a specific proposal row; they are exposed
only as tenant-wide aggregates via ``/summary`` + ``/insights``.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums                                                                       #
# --------------------------------------------------------------------------- #


class BidTypeCategory(str, Enum):
    """Keyword bucketing of the free-form ``bid_type`` field.

    Tested by substring match on the lowercased string:

      - ``PRESSURIZED`` — contains ``pressurized``, ``water``, or
        ``irrigation``.
      - ``STRUCTURES``  — contains ``structure`` or ``vault``.
      - ``CONCRETE``    — contains ``concrete``.
      - ``EARTHWORK``   — contains ``earth``, ``grading``, or ``excav``.
      - ``OTHER``       — anything else (or null).
    """

    PRESSURIZED = "pressurized"
    STRUCTURES = "structures"
    CONCRETE = "concrete"
    EARTHWORK = "earthwork"
    OTHER = "other"


class GeographyTier(str, Enum):
    """Where the proposal sits vs. the tenant's primary state.

    ``county`` in the mart is formatted ``"County Name, ST"``. We
    parse the trailing two-letter state code and compare against a
    tunable ``primary_state`` (default ``UT``).
    """

    IN_STATE = "in_state"
    OUT_OF_STATE = "out_of_state"
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------- #
# List / detail                                                               #
# --------------------------------------------------------------------------- #


class ProposalListRow(BaseModel):
    id: str = Field(
        ...,
        description=(
            "Stable hash of ``job|owner|bid_type`` (12-hex chars). "
            "Used in the ``/{proposal_id}`` detail URL."
        ),
    )
    job: str
    owner: str
    bid_type: str
    county: str | None = None
    state_code: str | None = Field(
        None,
        description=(
            "Two-letter state parsed from ``county`` (e.g. ``UT``). "
            "None when ``county`` is null or unparseable."
        ),
    )

    bid_type_category: BidTypeCategory = BidTypeCategory.OTHER
    geography_tier: GeographyTier = GeographyTier.UNKNOWN


class ProposalListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    sort_by: str
    sort_dir: Literal["asc", "desc"]
    items: list[ProposalListRow]


class ProposalDetail(BaseModel):
    """Single proposal detail.

    Until line-items are joinable, detail is just the header plus
    the derived fields.
    """

    id: str
    job: str
    owner: str
    bid_type: str
    county: str | None = None
    state_code: str | None = None

    bid_type_category: BidTypeCategory = BidTypeCategory.OTHER
    geography_tier: GeographyTier = GeographyTier.UNKNOWN


# --------------------------------------------------------------------------- #
# Line-item side: tenant-wide pool, not joined per-proposal.                  #
# --------------------------------------------------------------------------- #


class ProposalLineItem(BaseModel):
    """One row from ``mart_proposal_line_items`` (competitor pool)."""

    row_hash: str = Field(
        ..., description="Mart ``_row_hash`` — the line-item PK."
    )
    competitor: str | None = None
    design_fee: int | None = None
    cm_fee: int | None = None
    cm_monthly_fee: int | None = None
    contractor_ohp_fee: int | None = None
    contractor_bonds_ins: int | None = None
    contractor_co_markup: int | None = None
    city_budget: int | None = None
    contractor_start: datetime | None = None
    contractor_days: int | None = None
    contractor_projects: int | None = None
    pm_projects: int | None = None
    contractor_pm: str | None = None
    contractor_super: str | None = None
    reference_1: str | None = None
    reference_2: str | None = None
    reference_3: str | None = None


# --------------------------------------------------------------------------- #
# Summary (KPI tiles)                                                         #
# --------------------------------------------------------------------------- #


class ProposalsSummary(BaseModel):
    """KPI tiles at the top of the Proposals screen."""

    total_proposals: int = Field(
        ..., description="Rows in ``mart_proposals`` for this tenant.",
    )
    distinct_owners: int
    distinct_bid_types: int
    distinct_counties: int
    distinct_states: int = Field(
        0,
        description=(
            "Distinct two-letter state codes parsed from ``county``."
        ),
    )
    in_state_proposals: int = Field(
        0,
        description=(
            "Proposals whose parsed state matches the configured "
            "``primary_state``."
        ),
    )
    out_of_state_proposals: int = 0
    unknown_geography_proposals: int = 0

    total_line_items: int = Field(
        0,
        description=(
            "Rows in ``mart_proposal_line_items`` for this tenant "
            "(tenant-wide pool, not joinable to proposals yet)."
        ),
    )
    line_items_with_competitor: int = 0
    distinct_competitors: int = 0

    total_city_budget: int = Field(
        0,
        description=(
            "Sum of ``city_budget`` across line items (integer). "
            "0 when no line items carry a budget."
        ),
    )
    avg_city_budget: float = Field(
        0.0,
        description=(
            "Mean ``city_budget`` across line items with a non-null "
            "value. 0 when no line items qualify."
        ),
    )


# --------------------------------------------------------------------------- #
# Insights                                                                    #
# --------------------------------------------------------------------------- #


class BidTypeCategoryBreakdown(BaseModel):
    pressurized: int = 0
    structures: int = 0
    concrete: int = 0
    earthwork: int = 0
    other: int = 0


class GeographyTierBreakdown(BaseModel):
    in_state: int = 0
    out_of_state: int = 0
    unknown: int = 0


class SegmentCountRow(BaseModel):
    """Generic ``(segment, count)`` pair used for top-N owner / bid_type / county lists."""

    segment: str
    count: int


class CompetitorFrequencyRow(BaseModel):
    competitor: str
    line_item_count: int = Field(
        ...,
        description=(
            "Rows in ``mart_proposal_line_items`` carrying this "
            "competitor name."
        ),
    )


class FeeStatsRow(BaseModel):
    """Summary statistics for one numeric fee column in the line-items mart."""

    fee: str = Field(
        ...,
        description=(
            "Column name (``design_fee``, ``cm_fee``, etc.)."
        ),
    )
    count: int = Field(
        ...,
        description="Line items with a non-null value for this fee.",
    )
    min_value: int | None = None
    max_value: int | None = None
    avg_value: float | None = Field(
        None,
        description=(
            "Mean across non-null values. None when ``count`` is 0."
        ),
    )


class ProposalsInsights(BaseModel):
    bid_type_category_breakdown: BidTypeCategoryBreakdown
    geography_tier_breakdown: GeographyTierBreakdown

    top_owners: list[SegmentCountRow] = Field(
        default_factory=list,
        description="Top-N owners ranked by proposal count.",
    )
    top_bid_types: list[SegmentCountRow] = Field(
        default_factory=list,
        description="Top-N bid_types ranked by proposal count.",
    )
    top_counties: list[SegmentCountRow] = Field(
        default_factory=list,
        description="Top-N counties ranked by proposal count.",
    )
    top_states: list[SegmentCountRow] = Field(
        default_factory=list,
        description=(
            "Top-N state codes (parsed from county) ranked by count."
        ),
    )

    competitor_frequency: list[CompetitorFrequencyRow] = Field(
        default_factory=list,
        description=(
            "Top-N line-item competitors by frequency (tenant-wide "
            "pool, not joined per-proposal)."
        ),
    )
    fee_statistics: list[FeeStatsRow] = Field(
        default_factory=list,
        description=(
            "Per-fee stats across ``mart_proposal_line_items``: count, "
            "min, max, average. Covers the seven fee columns and "
            "``city_budget``."
        ),
    )
