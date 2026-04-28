"""vendors IngestJob — Firm Contacts.xlsx → mart_vendors.

No natural key available — falls back to row-hash dedupe. See
data_mapping.md § "Dedupe key conventions".
"""
from __future__ import annotations

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts.vendors.schema import TABLE_NAME

job = register_job(
    IngestJob(
        name="vendors",
        source_file="Firm Contacts.xlsx",
        target_table=TABLE_NAME,
        sheet_name="Firm Contacts",
        column_map={
            "Name": "name",
            "Firm Type": "firm_type",
            "Contact": "contact",
            "Title": "title",
            "Email": "email",
            "Phone": "phone",
            "Code 1": "code_1",
            "Code 2": "code_2",
            "Code 3": "code_3",
            "Code 4": "code_4",
            "Code 5": "code_5",
        },
        type_map={
            "name": str, "firm_type": str, "contact": str, "title": str,
            "email": str, "phone": str,
            "code_1": str, "code_2": str, "code_3": str, "code_4": str,
            "code_5": str,
        },
        dedupe_keys=["tenant_id", "_row_hash"],
    )
)
