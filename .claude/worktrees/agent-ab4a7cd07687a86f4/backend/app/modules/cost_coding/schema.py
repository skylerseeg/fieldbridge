"""Pydantic response models for the cost_coding module.

Primary entity: a **cost code** (HCSS ``activity_code``). One mart
row is one (estimate, activity_code) pair; we roll up across every
estimate a code appears in.

Three orthogonal classifications per code:
  - ``CostCategory``: which bucket dominates spend (labor / material /
    equipment / subcontract / mixed / zero).
  - ``CostSizeTier``: total-dollar magnitude (major / significant /
    minor / zero). Thresholds tunable per request.
  - ``UsageTier``: how many distinct estimates reference the code
    (heavy / regular / light / singleton).
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums                                                                       #
# --------------------------------------------------------------------------- #


class CostCategory(str, Enum):
    """Which cost bucket dominates this code's total direct cost.

    A bucket "dominates" when its share of the code's total direct
    cost crosses the dominance threshold (default 60%). If no single
    bucket dominates, the code is ``MIXED``. Codes with zero total
    direct cost are ``ZERO``.
    """

    LABOR = "labor"
    PERMANENT_MATERIAL = "permanent_material"
    CONSTRUCTION_MATERIAL = "construction_material"
    EQUIPMENT = "equipment"
    SUBCONTRACT = "subcontract"
    MIXED = "mixed"
    ZERO = "zero"


class CostSizeTier(str, Enum):
    """Dollar-magnitude bucket for a cost code."""

    MAJOR = "major"             # total_direct_cost >= major_cost_min
    SIGNIFICANT = "significant"  # >= significant_cost_min
    MINOR = "minor"             # > 0
    ZERO = "zero"               # == 0


class UsageTier(str, Enum):
    """How broadly the code is used across estimates."""

    HEAVY = "heavy"         # estimate_count >= heavy_min_estimates
    REGULAR = "regular"     # >= regular_min_estimates
    LIGHT = "light"         # 2..regular_min-1
    SINGLETON = "singleton"  # exactly 1 estimate


# --------------------------------------------------------------------------- #
# List / detail                                                               #
# --------------------------------------------------------------------------- #


class CostCodeListRow(BaseModel):
    id: str = Field(
        ...,
        description=(
            "Normalized activity code — used in the ``/{code_id}`` "
            "detail URL. Equal to ``code`` field."
        ),
    )
    code: str
    description: str | None = Field(
        None,
        description=(
            "Most-common activity description across occurrences. "
            "Ties broken by first-seen (alphabetical)."
        ),
    )
    major_code: str | None = Field(
        None,
        description=(
            "Prefix before the first dot in the code, e.g. ``1101.100`` "
            "→ ``1101``. None when the code has no dot."
        ),
    )

    estimate_count: int = Field(
        ..., description="Distinct estimates this code appears in."
    )
    total_man_hours: float = 0.0
    total_direct_cost: float = 0.0

    labor_cost: float = 0.0
    permanent_material_cost: float = 0.0
    construction_material_cost: float = 0.0
    equipment_cost: float = 0.0
    subcontract_cost: float = 0.0

    cost_category: CostCategory = CostCategory.ZERO
    size_tier: CostSizeTier = CostSizeTier.ZERO
    usage_tier: UsageTier = UsageTier.SINGLETON


class CostCodeListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    sort_by: str
    sort_dir: Literal["asc", "desc"]
    items: list[CostCodeListRow]


class CostCodeEstimateBreakdown(BaseModel):
    """One estimate's contribution to a cost code's rollup."""

    estimate_code: str
    estimate_name: str | None = None
    activity_description: str | None = None
    man_hours: float = 0.0
    direct_total_cost: float = 0.0
    labor_cost: float = 0.0
    permanent_material_cost: float = 0.0
    construction_material_cost: float = 0.0
    equipment_cost: float = 0.0
    subcontract_cost: float = 0.0


class CostCodeDetail(BaseModel):
    """Single cost-code detail — list fields plus per-estimate breakdown."""

    id: str
    code: str
    description: str | None = None
    major_code: str | None = None

    estimate_count: int
    total_man_hours: float = 0.0
    total_direct_cost: float = 0.0

    labor_cost: float = 0.0
    permanent_material_cost: float = 0.0
    construction_material_cost: float = 0.0
    equipment_cost: float = 0.0
    subcontract_cost: float = 0.0

    cost_category: CostCategory = CostCategory.ZERO
    size_tier: CostSizeTier = CostSizeTier.ZERO
    usage_tier: UsageTier = UsageTier.SINGLETON

    distinct_descriptions: int = Field(
        0,
        description=(
            "How many different activity_description values this code "
            "has carried across estimates. High values hint at coding "
            "drift worth reviewing."
        ),
    )
    estimates: list[CostCodeEstimateBreakdown] = Field(
        default_factory=list,
        description=(
            "Top estimates by direct cost (descending). Capped at the "
            "detail view's top-N limit."
        ),
    )


# --------------------------------------------------------------------------- #
# Summary (KPI tiles)                                                         #
# --------------------------------------------------------------------------- #


class CostCodingSummary(BaseModel):
    """KPI tiles at the top of the Cost Coding screen."""

    total_codes: int = Field(
        ..., description="Distinct activity codes in the directory."
    )
    total_activities: int = Field(
        ..., description="Raw mart row count (estimate x code pairs).",
    )
    distinct_estimates: int

    total_man_hours: float = 0.0
    total_direct_cost: float = 0.0
    total_labor_cost: float = 0.0
    total_permanent_material_cost: float = 0.0
    total_construction_material_cost: float = 0.0
    total_equipment_cost: float = 0.0
    total_subcontract_cost: float = 0.0

    # Coverage counts — how many distinct codes have $>0 in each bucket.
    codes_with_labor: int = 0
    codes_with_permanent_material: int = 0
    codes_with_construction_material: int = 0
    codes_with_equipment: int = 0
    codes_with_subcontract: int = 0

    uncosted_codes: int = Field(
        0,
        description=(
            "Codes with zero total direct cost across every estimate "
            "they appear in — candidate coding-hygiene gaps."
        ),
    )


# --------------------------------------------------------------------------- #
# Insights                                                                    #
# --------------------------------------------------------------------------- #


class CostCategoryBreakdown(BaseModel):
    """Count of codes in each dominant-category bucket."""

    labor: int = 0
    permanent_material: int = 0
    construction_material: int = 0
    equipment: int = 0
    subcontract: int = 0
    mixed: int = 0
    zero: int = 0


class SizeTierBreakdown(BaseModel):
    major: int = 0
    significant: int = 0
    minor: int = 0
    zero: int = 0


class UsageTierBreakdown(BaseModel):
    heavy: int = 0
    regular: int = 0
    light: int = 0
    singleton: int = 0


class CostCategoryMixRow(BaseModel):
    """Share of total spend attributable to one cost category."""

    category: CostCategory
    code_count: int
    total_direct_cost: float
    share_of_total: float = Field(
        ...,
        description=(
            "Fraction of overall direct cost this category represents. "
            "0.0 when total is zero."
        ),
    )


class MajorCodeRollup(BaseModel):
    """Aggregation by the pre-dot ``major_code`` prefix."""

    major_code: str
    code_count: int
    estimate_count: int
    total_direct_cost: float = 0.0
    total_man_hours: float = 0.0
    example_description: str | None = None


class TopCostCodeRow(BaseModel):
    """One cost code in a top-N insights list."""

    code: str
    description: str | None = None
    estimate_count: int
    total_direct_cost: float = 0.0
    total_man_hours: float = 0.0
    cost_category: CostCategory = CostCategory.ZERO


class CostCodingInsights(BaseModel):
    category_breakdown: CostCategoryBreakdown
    size_tier_breakdown: SizeTierBreakdown
    usage_tier_breakdown: UsageTierBreakdown

    category_mix: list[CostCategoryMixRow] = Field(
        default_factory=list,
        description="Per-category spend share across all codes (sums to ~1.0).",
    )

    top_by_cost: list[TopCostCodeRow] = Field(
        default_factory=list,
        description="Top-N codes by total direct cost (descending).",
    )
    top_by_usage: list[TopCostCodeRow] = Field(
        default_factory=list,
        description="Top-N codes by estimate_count (descending).",
    )
    top_by_hours: list[TopCostCodeRow] = Field(
        default_factory=list,
        description="Top-N codes by total_man_hours (descending).",
    )
    top_major_codes: list[MajorCodeRollup] = Field(
        default_factory=list,
        description="Top-N major-code prefixes by total direct cost.",
    )
    uncosted_codes: list[TopCostCodeRow] = Field(
        default_factory=list,
        description=(
            "Codes with ``total_direct_cost == 0`` across every "
            "estimate — candidate coding-hygiene gaps. Capped at "
            "top-N, alphabetical by code."
        ),
    )
