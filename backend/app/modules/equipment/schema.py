"""Pydantic response models for the equipment module.

All models are read-only API views. The underlying data shape is defined
in ``app.services.excel_marts.equipment_*.schema`` (pre-Vista) and will
migrate to Vista's ``emem``/``emwo`` tables in v2 without changing these.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums + shared primitives                                                   #
# --------------------------------------------------------------------------- #


class UtilizationBucket(str, Enum):
    """Classification of an asset's utilization posture.

    Tile counts on the Equipment screen: 67 under / 19 excessive / 14 good /
    5 issues. Thresholds are configurable in ``service.classify_bucket``.
    """

    UNDER = "under"
    EXCESSIVE = "excessive"
    GOOD = "good"
    ISSUES = "issues"


class OwnershipKind(str, Enum):
    OWNED = "owned"
    RENTED = "rented"


# --------------------------------------------------------------------------- #
# List / detail row shapes                                                    #
# --------------------------------------------------------------------------- #


class EquipmentListRow(BaseModel):
    """One row on the paginated equipment list endpoint."""

    id: str = Field(..., description="Stable identifier (truck/equipment name).")
    truck: str
    ownership: OwnershipKind
    tickets: int
    total_qty: float
    total_revenue: float
    last_ticket_date: datetime | None = None
    bucket: UtilizationBucket


class EquipmentListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    sort_by: str
    sort_dir: Literal["asc", "desc"]
    items: list[EquipmentListRow]


class EquipmentCurrentJob(BaseModel):
    """Current Vista emwo context joined through mart_work_orders."""

    job_number: str | None = None
    work_order: str | None = None
    status: Literal["open", "hold", "closed", "unknown"] | None = None
    open_date: datetime | None = None
    description: str | None = None


class EquipmentLastTransfer(BaseModel):
    """Latest tool/equipment movement from mart_equipment_transfers."""

    transfer_date: datetime | None = None
    location: str | None = None
    quantity: int | None = None
    requested_by: str | None = None
    user: str | None = None


class EquipmentStatusRow(BaseModel):
    """Field-facing live status row for one asset."""

    id: str = Field(..., description="Stable identifier (truck/equipment name).")
    truck: str
    bucket: UtilizationBucket
    ownership: OwnershipKind
    retired: bool
    retired_date: datetime | None = None
    tickets: int
    last_ticket_date: datetime | None = None
    days_since_last_ticket: int | None = None
    stale_ticket: bool = Field(
        False,
        description="True when no mart_equipment_utilization ticket in 14+ days.",
    )
    current_job: EquipmentCurrentJob
    last_transfer: EquipmentLastTransfer


class EquipmentStatusResponse(BaseModel):
    as_of: datetime
    stale_threshold_days: int
    total: int
    page: int
    page_size: int
    items: list[EquipmentStatusRow]


class RecentTicket(BaseModel):
    ticket_date: datetime
    ticket: str
    job: str | None = None
    material: str | None = None
    qty: float | None = None
    units: str | None = None
    price: float | None = None
    extended_price: float | None = None


class EquipmentDetail(BaseModel):
    id: str
    truck: str
    ownership: OwnershipKind
    bucket: UtilizationBucket
    tickets: int
    total_qty: float
    total_revenue: float
    first_ticket_date: datetime | None = None
    last_ticket_date: datetime | None = None
    cost_per_hour: float | None = Field(
        None,
        description=(
            "Revenue per recorded hour when `units` looks like hours; None "
            "when the asset has no hour-denominated tickets."
        ),
    )
    # Asset master fields from mart_asset_barcodes, only populated when the
    # truck name happens to encode a numeric barcode (rare — mostly null).
    manufacturer: str | None = None
    model: str | None = None
    material: str | None = None
    retired_date: datetime | None = None
    # Rental fields from mart_equipment_rentals, when ownership == rented.
    rental_company: str | None = None
    picked_up_date: datetime | None = None
    scheduled_return_date: datetime | None = None
    returned_date: datetime | None = None
    rental_rate: float | None = None
    rate_unit: str | None = None
    recent_tickets: list[RecentTicket] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Summary (KPI tiles)                                                         #
# --------------------------------------------------------------------------- #


class EquipmentSummary(BaseModel):
    """KPI tiles shown at the top of the Equipment screen.

    The four bucket counts mirror the screenshot (67/19/14/5 for VanCon).
    """

    total_assets: int
    owned_assets: int
    rented_assets: int
    tickets_30d: int
    revenue_30d: float
    bucket_under: int
    bucket_excessive: int
    bucket_good: int
    bucket_issues: int


# --------------------------------------------------------------------------- #
# Insights                                                                    #
# --------------------------------------------------------------------------- #


class BucketBreakdown(BaseModel):
    under: int
    excessive: int
    good: int
    issues: int


class FuelCostPerHour(BaseModel):
    id: str
    truck: str
    hours: float
    revenue: float
    cost_per_hour: float


class OwnershipMetrics(BaseModel):
    count: int
    total_revenue: float
    total_tickets: int
    avg_tickets_per_asset: float


class RentalMetrics(BaseModel):
    count: int
    active_rentals: int
    total_rate_committed: float
    avg_rate: float


class RentalVsOwned(BaseModel):
    owned: OwnershipMetrics
    rented: RentalMetrics


class EquipmentInsights(BaseModel):
    as_of: datetime
    utilization_buckets: BucketBreakdown
    fuel_cost_per_hour_by_asset: list[FuelCostPerHour]
    rental_vs_owned: RentalVsOwned
