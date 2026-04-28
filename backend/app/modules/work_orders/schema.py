"""Pydantic response models for the work-orders module.

Vista status codes (``O`` / ``C`` / ``H``) and priority codes (``1`` /
``2`` / ``3``) are kept as-is at the storage layer and normalized into
friendly labels here for API consumers.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums                                                                       #
# --------------------------------------------------------------------------- #


class WorkOrderStatus(str, Enum):
    """Vista emwo.Status values, normalized to lowercase labels."""

    OPEN = "open"       # Vista: O
    CLOSED = "closed"   # Vista: C
    HOLD = "hold"       # Vista: H
    UNKNOWN = "unknown"


class WorkOrderPriority(str, Enum):
    CRITICAL = "critical"  # Vista: 1
    HIGH = "high"          # Vista: 2
    NORMAL = "normal"      # Vista: 3
    UNKNOWN = "unknown"


class AgingBucket(str, Enum):
    """Age bucket for open WOs — used by the list endpoint's filter."""

    FRESH = "fresh"        # <= 7 days
    AGING = "aging"        # 8-30 days
    STALE = "stale"        # 31-90 days
    CRITICAL = "critical"  # > 90 days


# --------------------------------------------------------------------------- #
# List / detail rows                                                          #
# --------------------------------------------------------------------------- #


class WorkOrderListRow(BaseModel):
    id: str = Field(..., description="Work order number (stable identifier).")
    work_order: str
    equipment: str | None = None
    description: str | None = None
    status: WorkOrderStatus
    priority: WorkOrderPriority
    open_date: datetime | None = None
    closed_date: datetime | None = None
    age_days: int | None = Field(
        None,
        description=(
            "Days since open_date. For closed WOs this is the lifespan; for "
            "open WOs it's the current age."
        ),
    )
    overdue: bool = Field(
        False,
        description=(
            "True when the WO is still open past the overdue threshold "
            "(default 30 days — configurable at the /insights endpoint)."
        ),
    )
    mechanic: str | None = None
    total_cost: float | None = None
    estimated_cost: float | None = None


class WorkOrderListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    sort_by: str
    sort_dir: Literal["asc", "desc"]
    items: list[WorkOrderListRow]


class WorkOrderDetail(BaseModel):
    id: str
    work_order: str
    equipment: str | None = None
    description: str | None = None
    status: WorkOrderStatus
    priority: WorkOrderPriority
    requested_by: str | None = None
    mechanic: str | None = None
    job_number: str | None = None
    open_date: datetime | None = None
    closed_date: datetime | None = None
    age_days: int | None = None
    overdue: bool = False
    labor_hours: float | None = None
    estimated_hours: float | None = None
    parts_cost: float | None = None
    total_cost: float | None = None
    estimated_cost: float | None = None
    cost_variance: float | None = Field(
        None, description="total_cost - estimated_cost. None when either is missing.",
    )
    cost_variance_pct: float | None = Field(
        None, description="cost_variance / estimated_cost * 100. None when budget is 0/None.",
    )


# --------------------------------------------------------------------------- #
# Summary (KPI tiles)                                                         #
# --------------------------------------------------------------------------- #


class WorkOrderSummary(BaseModel):
    """KPI tiles shown at the top of the Work Orders screen."""

    total_work_orders: int
    open_count: int
    closed_count: int
    hold_count: int
    overdue_count: int
    overdue_threshold_days: int
    avg_age_days_open: float
    total_cost_to_date: float
    total_budget: float


# --------------------------------------------------------------------------- #
# Insights                                                                    #
# --------------------------------------------------------------------------- #


class StatusCounts(BaseModel):
    """Open count by status — Vista labels normalized to lowercase.

    The explicit ``unknown`` bucket catches malformed status codes so we
    don't silently drop rows during a Vista migration.
    """

    open: int
    closed: int
    hold: int
    unknown: int


class CostVsBudget(BaseModel):
    cost_to_date: float
    budget: float
    variance: float = Field(
        ..., description="cost_to_date - budget (positive = over budget).",
    )
    variance_pct: float | None = Field(
        None,
        description="variance / budget * 100. None when budget is 0.",
    )


class WorkOrderInsights(BaseModel):
    as_of: datetime
    overdue_threshold_days: int
    status_counts: StatusCounts
    avg_age_days_open: float
    overdue_count: int
    cost_vs_budget: CostVsBudget
