"""vendor_enrichments — overlay table on top of mart_vendors.

Source: none (no Excel sheet). Rows are written by the vendors module's
``POST /api/vendors/enrichments/{vendor_id}`` endpoint and consumed by
the read paths via ``mart_vendors LEFT JOIN mart_vendor_enrichments``,
with non-empty enrichment values winning over the source row.

Dedupe: composite ``(tenant_id, vendor_id)`` — one overlay row per
vendor per tenant. The endpoint upserts on this key.

Spec: ``backend/app/modules/vendors/PROPOSED_CHANGES.md``
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.services.excel_marts._base import (
    Column, DateTime, String, Text, mart,
)

TABLE_NAME = "mart_vendor_enrichments"


# Overlay shape mirrors the writable subset of mart_vendors plus
# created_at/updated_at audit fields. firm_type is stored as a string
# (rather than an enum at the DB layer) so the canonical FirmType enum
# lives only in app.modules.vendors.schema — the mart stays
# enum-agnostic and the read path validates on the way out.
table = mart(
    TABLE_NAME,
    Column("vendor_id", String(255), primary_key=True, nullable=False),

    # Writable contact fields. Each can independently override the
    # corresponding mart_vendors field; "" / None means "no override".
    Column("contact", String(200)),
    Column("title", String(120)),
    Column("email", String(200)),
    Column("phone", String(40)),
    Column("firm_type", String(120)),

    # CSI / firm-type code slots. Width is 80 (vs. mart_vendors 40)
    # because enrichment may carry "code-description" composite strings
    # like "032213-Reinforcing Bars". Five slots match mart_vendors.
    Column("code_1", String(80)),
    Column("code_2", String(80)),
    Column("code_3", String(80)),
    Column("code_4", String(80)),
    Column("code_5", String(80)),

    Column("notes", Text),

    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)


class VendorEnrichmentRow(BaseModel):
    """ORM-shape mirror of ``mart_vendor_enrichments``.

    Used by the vendors module write path; not consumed directly by the
    read path (which goes through raw SQL + the response Pydantic models
    in ``app.modules.vendors.schema``).
    """

    tenant_id: str
    vendor_id: str
    contact: str | None = None
    title: str | None = None
    email: str | None = None
    phone: str | None = None
    firm_type: str | None = None
    code_1: str | None = None
    code_2: str | None = None
    code_3: str | None = None
    code_4: str | None = None
    code_5: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
