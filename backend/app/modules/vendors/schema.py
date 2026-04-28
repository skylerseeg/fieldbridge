"""Pydantic response models for the vendors module.

Primary entity: a **vendor** — one row of ``mart_vendors``, keyed by
its normalized name (whitespace stripped & collapsed). This mart is
purely directory data — no transaction dollars, no activity — so
the module's value is in *data-health* metrics rather than P&L.

Three orthogonal classifications per vendor:
  - ``FirmType``: Supplier / Contractor / Service / Internal / Unknown.
  - ``ContactStatus``: how complete the contact fields are.
  - ``CodingStatus``: coded (>=1 CSI code on file) vs uncoded.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums                                                                       #
# --------------------------------------------------------------------------- #


class FirmType(str, Enum):
    """Normalized firm type."""

    SUPPLIER = "supplier"
    CONTRACTOR = "contractor"
    SERVICE = "service"
    INTERNAL = "internal"
    UNKNOWN = "unknown"   # null or unrecognized value


class ContactStatus(str, Enum):
    """Contact-data completeness tier.

    Mirrors an equipment-style 4-tile dashboard: complete / partial /
    minimal / empty. Useful for data-hygiene sprints.
    """

    COMPLETE = "complete"   # name + contact + email + phone
    PARTIAL = "partial"     # name + any one of (contact/email/phone)
    MINIMAL = "minimal"     # name only (no reachable channel)
    EMPTY = "empty"         # no name at all (stub/ghost row)


class CodingStatus(str, Enum):
    """CSI coding coverage."""

    CODED = "coded"       # at least one CSI code on file
    UNCODED = "uncoded"   # no CSI codes


# --------------------------------------------------------------------------- #
# List / detail                                                               #
# --------------------------------------------------------------------------- #


class VendorListRow(BaseModel):
    id: str = Field(
        ...,
        description=(
            "Whitespace-normalized vendor name. Used in the "
            "``/{vendor_id}`` detail URL. ``EMPTY`` rows (null name) use "
            "``__empty__<row_hash>`` so they remain addressable."
        ),
    )
    name: str | None = Field(
        None,
        description=(
            "Display name. None for ``EMPTY`` contact-status rows."
        ),
    )

    firm_type: FirmType = FirmType.UNKNOWN
    firm_type_raw: str | None = Field(
        None, description="Original mart value (e.g. ``Supplier``).",
    )

    contact: str | None = None
    title: str | None = None
    email: str | None = None
    phone: str | None = None

    codes: list[str] = Field(
        default_factory=list,
        description="Non-null CSI codes on file (up to 5).",
    )
    code_count: int = 0
    primary_division: str | None = Field(
        None,
        description=(
            "Two-digit MasterFormat division from ``code_1`` "
            "(e.g. ``03`` for Concrete). None when uncoded."
        ),
    )

    contact_status: ContactStatus = ContactStatus.EMPTY
    coding_status: CodingStatus = CodingStatus.UNCODED
    enriched: bool = Field(
        False,
        description="True when a row has an overlay in mart_vendor_enrichments.",
    )
    enriched_at: str | None = Field(
        None,
        description="ISO timestamp from mart_vendor_enrichments.updated_at.",
    )


class VendorListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    sort_by: str
    sort_dir: Literal["asc", "desc"]
    items: list[VendorListRow]


class VendorDetail(BaseModel):
    """Single-vendor detail — list fields plus division labels."""

    id: str
    name: str | None = None

    firm_type: FirmType = FirmType.UNKNOWN
    firm_type_raw: str | None = None

    contact: str | None = None
    title: str | None = None
    email: str | None = None
    phone: str | None = None

    codes: list[str] = Field(default_factory=list)
    code_count: int = 0
    primary_division: str | None = None
    divisions: list[str] = Field(
        default_factory=list,
        description=(
            "Sorted, distinct two-digit divisions across all codes on file."
        ),
    )

    contact_status: ContactStatus = ContactStatus.EMPTY
    coding_status: CodingStatus = CodingStatus.UNCODED
    enriched: bool = False
    enriched_at: str | None = None
    enrichment_notes: str | None = None


class VendorEnrichmentRequest(BaseModel):
    """Write payload for the vendor enrichment overlay table."""

    contact: str | None = Field(None, max_length=200)
    title: str | None = Field(None, max_length=120)
    email: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=40)
    firm_type: FirmType | None = None
    codes: list[str] = Field(default_factory=list, max_length=5)
    notes: str | None = None


# --------------------------------------------------------------------------- #
# Summary (KPI tiles)                                                         #
# --------------------------------------------------------------------------- #


class VendorSummary(BaseModel):
    """KPI tiles at the top of the Vendors screen."""

    total_vendors: int

    # Contact health
    with_name: int
    with_contact: int
    with_email: int
    with_phone: int
    complete_contact: int = Field(
        ...,
        description="Name + contact + email + phone all present.",
    )

    # Coding coverage
    coded_vendors: int
    uncoded_vendors: int
    distinct_codes: int
    distinct_divisions: int

    # Firm-type counts (flattened for easy tile rendering)
    suppliers: int
    contractors: int
    services: int
    internal: int
    unknown_firm_type: int


# --------------------------------------------------------------------------- #
# Insights                                                                    #
# --------------------------------------------------------------------------- #


class FirmTypeBreakdown(BaseModel):
    supplier: int
    contractor: int
    service: int
    internal: int
    unknown: int


class ContactHealthBreakdown(BaseModel):
    complete: int
    partial: int
    minimal: int
    empty: int


class CodingBreakdown(BaseModel):
    coded: int
    uncoded: int


class DivisionMixRow(BaseModel):
    """One two-digit MasterFormat division rolled up across vendors."""

    division: str = Field(..., description='Two-digit division (e.g. "03").')
    vendor_count: int = Field(
        ...,
        description="Distinct vendors with at least one code in this division.",
    )
    code_count: int = Field(
        ...,
        description=(
            "Total code occurrences in this division across the directory "
            "(a vendor with two codes in the same division counts twice)."
        ),
    )
    example_code: str | None = Field(
        None,
        description="One representative code from this division (for labels).",
    )


class CodeMixRow(BaseModel):
    """One CSI code and how many vendors claim it."""

    code: str
    vendor_count: int
    top_firm_type: FirmType = FirmType.UNKNOWN


class VendorDepthRow(BaseModel):
    """Vendors with multi-code CSI coverage (versatile subs)."""

    id: str
    name: str | None = None
    code_count: int
    codes: list[str] = Field(default_factory=list)
    firm_type: FirmType = FirmType.UNKNOWN


class VendorsInsights(BaseModel):
    firm_type_breakdown: FirmTypeBreakdown
    contact_health: ContactHealthBreakdown
    coding_breakdown: CodingBreakdown

    top_codes: list[CodeMixRow] = Field(
        default_factory=list,
        description="Top-N CSI codes by vendor count.",
    )
    top_divisions: list[DivisionMixRow] = Field(
        default_factory=list,
        description="Top-N two-digit divisions by vendor count.",
    )
    thin_divisions: list[DivisionMixRow] = Field(
        default_factory=list,
        description=(
            "Divisions with vendor_count <= ``thin_division_max`` — "
            "candidate gaps to recruit subs into."
        ),
    )
    depth_leaders: list[VendorDepthRow] = Field(
        default_factory=list,
        description=(
            "Top-N vendors ranked by CSI code_count (descending). "
            "Identifies versatile multi-trade subs."
        ),
    )
