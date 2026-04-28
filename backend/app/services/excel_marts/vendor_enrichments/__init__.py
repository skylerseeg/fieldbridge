"""vendor_enrichments mart — overlay on top of mart_vendors.

No Excel ingest job: rows are written exclusively by the
``app.modules.vendors`` enrichment endpoint (POST /api/vendors/
enrichments/{vendor_id}). The Table is registered on
``Base.metadata`` so ``scripts/create_mart_tables.py`` builds it; the
:mod:`app.modules.vendors` service reads from it via LEFT JOIN against
``mart_vendors``.

Excluded from ``MART_MODULES`` for the same reason ``work_orders`` and
``predictive_maintenance`` are — ``list_marts()`` describes ingest
jobs, and overlay tables don't have one.
"""
from app.services.excel_marts.vendor_enrichments.schema import (
    TABLE_NAME,
    VendorEnrichmentRow,
    table,
)

__all__ = [
    "TABLE_NAME",
    "VendorEnrichmentRow",
    "table",
]
