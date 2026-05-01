"""Pydantic response models for the fleet_pnl module.

Primary entity: a **truck** (VanCon's trucks are keyed by their
tag — e.g. ``TK149``). Each row is a rollup of its haul-ticket
activity from ``mart_equipment_utilization``: revenue, quantities
hauled, invoiced vs. uninvoiced dollars, jobs/vendors served, and
whether the truck is owned or a lessor (rented-in).

Rental-in costs from ``mart_equipment_rentals`` are attributed to
the fleet at aggregate level only (one row per rental contract is
keyed by equipment description + vendor, not by VanCon truck tag),
so they surface on ``/summary`` and ``/insights`` rather than on
per-truck rows.

Three orthogonal classifications per truck:
  - ``LessorFlag``: owned, lessor, mixed (tickets flagged both ways),
    or unknown (no is_lessor data).
  - ``InvoiceBucket``: how far along each truck's A/R is — the
    classic "we hauled it, did we bill it?" PM question.
  - ``UtilizationBucket``: tier by ticket count (tunable thresholds).
    Mirrors the equipment dashboard's 67/19/14/5-style tiles without
    needing hour meters — ticket volume is our proxy for fleet use.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums                                                                       #
# --------------------------------------------------------------------------- #


class LessorFlag(str, Enum):
    """Is this truck on VanCon's books or rented-in?"""

    OWNED = "owned"
    LESSOR = "lessor"
    MIXED = "mixed"      # at least one ticket each flagged owned+lessor
    UNKNOWN = "unknown"  # no is_lessor data


class InvoiceBucket(str, Enum):
    """Per-truck invoicing completeness."""

    FULLY_INVOICED = "fully_invoiced"
    PARTIALLY_INVOICED = "partially_invoiced"
    UNINVOICED = "uninvoiced"
    UNKNOWN = "unknown"  # no invoiced data at all (edge case)


class UtilizationBucket(str, Enum):
    """Ticket-volume tier.

    Thresholds are tunable via query params so a fleet manager can
    calibrate against their own data — the defaults are set for the
    VanCon reference dataset (~20 trucks, ~8k tickets over the
    active window).
    """

    IDLE = "idle"                        # 0 tickets (unreachable from rollup)
    UNDERUTILIZED = "underutilized"      # ticket_count <= underutilized_max
    HEALTHY = "healthy"                   # between the two thresholds
    HEAVILY_UTILIZED = "heavily_utilized"  # ticket_count >= heavy_min


# --------------------------------------------------------------------------- #
# List / detail                                                               #
# --------------------------------------------------------------------------- #


class TruckListRow(BaseModel):
    id: str = Field(
        ...,
        description=(
            "Truck tag (e.g. ``TK149``). Used in the ``/{truck_id}`` "
            "detail URL."
        ),
    )
    truck: str = Field(..., description="Canonical truck tag.")

    # --- volume / revenue ---
    ticket_count: int = Field(
        ..., description="Haul tickets attributed to this truck.",
    )
    total_qty: float = Field(
        ..., description="Sum of ticket ``qty`` (units vary per ticket).",
    )
    revenue: float = Field(
        ..., description="Sum of ``extended_price`` across tickets.",
    )
    avg_price_per_ticket: float | None = Field(
        None,
        description=(
            "``revenue / ticket_count``. None when ticket_count is 0."
        ),
    )

    # --- invoicing ---
    invoiced_count: int
    invoiced_revenue: float
    uninvoiced_revenue: float = Field(
        ...,
        description=(
            "Revenue on tickets whose ``invoiced`` flag is false. "
            "A/R risk surface."
        ),
    )
    invoice_rate: float | None = Field(
        None,
        description=(
            "invoiced_count / ticket_count (fractional, 0.0–1.0). "
            "None when ticket_count is 0."
        ),
    )

    # --- breadth ---
    jobs_served: int = Field(..., description="Distinct jobs hauled for.")
    vendors_served: int = Field(..., description="Distinct vendors hauled from.")

    # --- active window ---
    first_ticket: datetime | None = None
    last_ticket: datetime | None = None
    active_days: int | None = Field(
        None,
        description=(
            "(last_ticket - first_ticket).days + 1. None when no dated "
            "tickets."
        ),
    )

    # --- classifications ---
    lessor_flag: LessorFlag = LessorFlag.UNKNOWN
    invoice_bucket: InvoiceBucket = InvoiceBucket.UNKNOWN
    utilization_bucket: UtilizationBucket = UtilizationBucket.IDLE

    # --- narrative labels (top-by-ticket-count) ---
    top_material: str | None = None
    top_vendor: str | None = None
    top_job: str | None = None
    top_driver: str | None = None


class TruckListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    sort_by: str
    sort_dir: Literal["asc", "desc"]
    items: list[TruckListRow]


class FleetTicketPoint(BaseModel):
    """One haul ticket, slimmed down for detail views."""

    ticket: str | None = None
    ticket_date: datetime | None = None
    job: str | None = None
    vendor: str | None = None
    pit: str | None = None
    material: str | None = None
    driver: str | None = None
    qty: float | None = None
    units: str | None = None
    price: float | None = None
    extended_price: float | None = None
    invoiced: bool | None = None
    invoice_number: str | None = None


class FleetMonthlyPoint(BaseModel):
    """Truck activity rolled up to one calendar month."""

    month: datetime
    ticket_count: int
    revenue: float
    qty: float


class FleetMixRow(BaseModel):
    """Generic top-N mix row — used for vendor/material/job/driver."""

    label: str
    ticket_count: int
    revenue: float
    qty: float


class FleetTruckDetail(BaseModel):
    """Single-truck detail — list fields plus time series and mixes."""

    id: str
    truck: str

    ticket_count: int
    total_qty: float
    revenue: float
    avg_price_per_ticket: float | None = None

    invoiced_count: int
    invoiced_revenue: float
    uninvoiced_revenue: float
    invoice_rate: float | None = None

    jobs_served: int
    vendors_served: int

    first_ticket: datetime | None = None
    last_ticket: datetime | None = None
    active_days: int | None = None

    lessor_flag: LessorFlag = LessorFlag.UNKNOWN
    invoice_bucket: InvoiceBucket = InvoiceBucket.UNKNOWN
    utilization_bucket: UtilizationBucket = UtilizationBucket.IDLE

    top_material: str | None = None
    top_vendor: str | None = None
    top_job: str | None = None
    top_driver: str | None = None

    recent_tickets: list[FleetTicketPoint] = Field(
        default_factory=list,
        description="Up to 20 most-recent tickets, newest first.",
    )
    monthly_series: list[FleetMonthlyPoint] = Field(
        default_factory=list,
        description="Revenue/tickets per calendar month, chronological.",
    )
    vendor_mix: list[FleetMixRow] = Field(default_factory=list)
    material_mix: list[FleetMixRow] = Field(default_factory=list)
    job_mix: list[FleetMixRow] = Field(default_factory=list)
    driver_mix: list[FleetMixRow] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Summary (KPI tiles)                                                         #
# --------------------------------------------------------------------------- #


class FleetSummary(BaseModel):
    """KPI tiles at the top of the Fleet P&L screen."""

    total_trucks: int = Field(..., description="Distinct trucks with tickets.")
    total_tickets: int
    total_qty: float
    total_revenue: float

    # A/R health
    invoiced_revenue: float
    uninvoiced_revenue: float
    invoice_rate: float | None = Field(
        None,
        description=(
            "Fleet-wide invoiced_count / ticket_count (fraction). "
            "None when there are no tickets."
        ),
    )

    # Ownership mix
    owned_trucks: int
    lessor_trucks: int
    mixed_trucks: int
    unknown_ownership_trucks: int

    # Active window
    first_ticket: datetime | None = None
    last_ticket: datetime | None = None
    active_days: int | None = None

    # Breadth
    unique_jobs: int
    unique_vendors: int
    unique_drivers: int

    # Rental-in cost side (separate data source)
    rental_contracts: int = Field(
        ...,
        description="Active rental-in records from mart_equipment_rentals.",
    )
    rental_monthly_cost: float = Field(
        ...,
        description=(
            "Sum of ``rate`` across rentals whose ``rate_unit`` is monthly."
        ),
    )


# --------------------------------------------------------------------------- #
# Insights                                                                    #
# --------------------------------------------------------------------------- #


class UtilizationBreakdown(BaseModel):
    """Truck counts in each utilization tier.

    Mirrors the equipment-dashboard 4-tile layout (under/healthy/heavy/
    idle) — fleet_pnl's analogue of 67/19/14/5.
    """

    idle: int
    underutilized: int
    healthy: int
    heavily_utilized: int


class InvoiceBreakdown(BaseModel):
    fully_invoiced: int
    partially_invoiced: int
    uninvoiced: int
    unknown: int


class RentalInSummary(BaseModel):
    """Snapshot of rental-in activity from ``mart_equipment_rentals``."""

    contracts: int = Field(..., description="Rental rows on file.")
    active_contracts: int = Field(
        ...,
        description=(
            "Rentals with ``returned_date`` null — still out in the field."
        ),
    )
    rpo_contracts: int = Field(
        ..., description="Rental-purchase-option rows (``is_rpo`` true).",
    )
    total_monthly_cost: float = Field(
        ...,
        description="Sum of rate across rentals priced monthly.",
    )
    total_hourly_cost: float = Field(
        ...,
        description="Sum of rate across rentals priced hourly.",
    )
    top_rental_vendors: list[FleetMixRow] = Field(
        default_factory=list,
        description=(
            "Top rental companies by contract count. ``revenue`` on each "
            "row is the summed monthly-equivalent rate, ``qty`` is 0."
        ),
    )


class TruckMoneyRow(BaseModel):
    """One row in a top-N truck list (revenue, uninvoiced, etc.)."""

    id: str
    truck: str
    value: float = Field(
        ...,
        description=(
            "The amount that got this row into the list (revenue $, "
            "uninvoiced $, ticket_count, etc.)."
        ),
    )
    ticket_count: int | None = None
    revenue: float | None = None


class FleetPnlInsights(BaseModel):
    as_of: datetime
    underutilized_max_tickets: int
    heavily_utilized_min_tickets: int

    utilization_breakdown: UtilizationBreakdown
    invoice_breakdown: InvoiceBreakdown
    rental_in: RentalInSummary

    top_revenue: list[TruckMoneyRow] = Field(
        default_factory=list,
        description="Top-N trucks by total revenue.",
    )
    top_uninvoiced: list[TruckMoneyRow] = Field(
        default_factory=list,
        description=(
            "Top-N trucks by uninvoiced revenue — A/R collection surface."
        ),
    )
    top_underutilized: list[TruckMoneyRow] = Field(
        default_factory=list,
        description=(
            "Bottom-N trucks by ticket_count (ascending). ``value`` is "
            "ticket_count."
        ),
    )
    top_vendors: list[FleetMixRow] = Field(
        default_factory=list,
        description="Top-N vendors fleet-wide by revenue.",
    )
    top_materials: list[FleetMixRow] = Field(
        default_factory=list,
        description="Top-N materials fleet-wide by revenue.",
    )
    top_jobs: list[FleetMixRow] = Field(
        default_factory=list,
        description="Top-N jobs fleet-wide by revenue.",
    )
