"""Pydantic response models for the timecards module.

We expose one entity per job class (``class_name``), joining
``mart_fte_class_actual`` with ``mart_fte_class_projected`` on
class_name. Overtime + overhead metrics are derived on the fly.

Variance status thresholds (`_VARIANCE_OK_BAND`) are intentionally
generous — FTE planning is noisy and we only flag meaningful swings.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums                                                                       #
# --------------------------------------------------------------------------- #


class VarianceStatus(str, Enum):
    """Coloring for the variance column.

    ``over`` / ``under`` trigger attention; ``on_track`` is green.
    """

    UNDER = "under"         # actual_avg is <10% of projected_avg (understaffed)
    ON_TRACK = "on_track"   # within ±10% of projected
    OVER = "over"           # actual_avg is >10% over projected (overstaffed)
    UNKNOWN = "unknown"     # projected is missing or zero


# --------------------------------------------------------------------------- #
# List / detail                                                               #
# --------------------------------------------------------------------------- #


class TimecardListRow(BaseModel):
    id: str = Field(..., description="Job class name (stable identifier).")
    class_name: str
    code: str | None = None
    craft_class: str | None = None

    monthly_hours: float | None = Field(
        None,
        description=(
            "Target hours per FTE per month (budget). Compared against "
            "``last_month_actuals`` to derive overtime."
        ),
    )
    last_month_actuals: float | None = Field(
        None,
        description="Actual hours per FTE last month.",
    )

    actual_avg_fte: float | None = Field(
        None,
        description="Rolling 12-month average FTE headcount (from actuals mart).",
    )
    projected_avg_fte: float | None = Field(
        None,
        description="Rolling 12-month average projected FTE (from projected mart).",
    )
    variance: float | None = Field(
        None,
        description="actual_avg_fte - projected_avg_fte (positive = overstaffed).",
    )
    variance_pct: float | None = Field(
        None,
        description=(
            "variance / projected_avg_fte * 100. None when projected is "
            "0 or missing."
        ),
    )
    variance_status: VarianceStatus = VarianceStatus.UNKNOWN

    overtime_hours: float | None = Field(
        None,
        description=(
            "max(0, last_month_actuals - monthly_hours). Hours per FTE "
            "above the monthly target in the last reported month."
        ),
    )
    overtime_pct: float | None = Field(
        None,
        description="overtime_hours / monthly_hours * 100.",
    )


class TimecardListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    sort_by: str
    sort_dir: Literal["asc", "desc"]
    items: list[TimecardListRow]


class MonthlyPoint(BaseModel):
    """One month of FTE data. Either actual or projected fills in."""

    month: str = Field(..., description="Month label, e.g. 'Feb 24' or 'Apr 26'.")
    actual: float | None = None
    projected: float | None = None


class TimecardDetail(BaseModel):
    id: str
    class_name: str
    code: str | None = None
    craft_class: str | None = None

    monthly_hours: float | None = None
    last_month_actuals: float | None = None

    actual_avg_fte: float | None = None
    projected_avg_fte: float | None = None
    variance: float | None = None
    variance_pct: float | None = None
    variance_status: VarianceStatus = VarianceStatus.UNKNOWN

    overtime_hours: float | None = None
    overtime_pct: float | None = None

    monthly_breakdown: list[MonthlyPoint] = Field(
        default_factory=list,
        description=(
            "Union of actual + projected months, ordered chronologically. "
            "Actual months populate ``actual``; projected months populate "
            "``projected``. No overlap today — actuals run Feb 24 – Jan 25 "
            "and projections Apr 26 – Mar 29."
        ),
    )


# --------------------------------------------------------------------------- #
# Summary (KPI tiles)                                                         #
# --------------------------------------------------------------------------- #


class TimecardSummary(BaseModel):
    """KPI tiles at the top of the Timecards screen."""

    total_classes: int
    total_overhead_departments: int
    total_job_types: int

    total_actual_fte: float = Field(
        ..., description="Sum of avg_12mo actual FTE across all classes.",
    )
    total_projected_fte: float = Field(
        ..., description="Sum of avg_12mo projected FTE across all classes.",
    )
    total_variance_pct: float | None = Field(
        None,
        description=(
            "(total_actual - total_projected) / total_projected * 100. "
            "None when total_projected is 0."
        ),
    )

    avg_overtime_pct: float = Field(
        ...,
        description=(
            "Mean overtime_pct across classes where monthly_hours is "
            "set. Expressed as %, e.g. 5.0 = 5%."
        ),
    )
    classes_with_overtime: int = Field(
        ...,
        description="Number of classes where last_month_actuals > monthly_hours.",
    )

    overhead_ratio_pct: float | None = Field(
        None,
        description=(
            "Overhead FTE / (overhead + direct) FTE * 100. None when both "
            "totals are zero."
        ),
    )


# --------------------------------------------------------------------------- #
# Insights                                                                    #
# --------------------------------------------------------------------------- #


class VarianceByClass(BaseModel):
    class_name: str
    actual_avg_fte: float | None = None
    projected_avg_fte: float | None = None
    variance: float | None = None
    variance_pct: float | None = None
    variance_status: VarianceStatus = VarianceStatus.UNKNOWN


class OvertimeByClass(BaseModel):
    class_name: str
    monthly_hours: float | None = None
    last_month_actuals: float | None = None
    overtime_hours: float | None = None
    overtime_pct: float | None = None


class OverheadRatio(BaseModel):
    overhead_fte: float = Field(
        ..., description="Sum of avg_12mo across all overhead departments.",
    )
    direct_fte: float = Field(
        ..., description="Sum of avg_12mo across all direct-labor job classes.",
    )
    ratio_pct: float | None = Field(
        None,
        description=(
            "overhead_fte / (overhead_fte + direct_fte) * 100. None when "
            "both are zero."
        ),
    )


class TimecardInsights(BaseModel):
    as_of: datetime
    variance_band_pct: float = Field(
        ...,
        description=(
            "The ±% band used to classify variance_status=on_track. "
            "Defaults to 10.0."
        ),
    )

    variance_over: list[VarianceByClass] = Field(
        default_factory=list,
        description="Top-N classes where actual exceeds projected (overstaffed).",
    )
    variance_under: list[VarianceByClass] = Field(
        default_factory=list,
        description="Top-N classes where actual trails projected (understaffed).",
    )

    overtime_leaders: list[OvertimeByClass] = Field(
        default_factory=list,
        description="Top-N classes by overtime_pct.",
    )

    overhead_ratio: OverheadRatio
