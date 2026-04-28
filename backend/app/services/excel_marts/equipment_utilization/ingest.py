"""equipment_utilization IngestJob."""
from __future__ import annotations

from datetime import datetime

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts.equipment_utilization.schema import TABLE_NAME

job = register_job(
    IngestJob(
        name="equipment_utilization",
        source_file="Equipment Utilization.xlsx",
        target_table=TABLE_NAME,
        sheet_name="Equipment Utilization",
        column_map={
            "Job": "job",
            "Images": "images",
            "Ticket Date": "ticket_date",
            "Ticket": "ticket",
            "Is Lessor": "is_lessor",
            "Invoiced": "invoiced",
            "Invoice Number": "invoice_number",
            "Invoice Date": "invoice_date",
            "Price": "price",
            "Extended Price": "extended_price",
            "Vendor": "vendor",
            "Pit": "pit",
            "Material": "material",
            "Truck": "truck",
            "Trailer 1": "trailer_1",
            "Trailer 2": "trailer_2",
            "Qty": "qty",
            "Units": "units",
            "Driver": "driver",
            "Notes": "notes",
        },
        type_map={
            "job": str,
            "images": str,
            "ticket_date": datetime,
            "ticket": str,
            "is_lessor": bool,
            "invoiced": bool,
            "invoice_number": str,
            "invoice_date": datetime,
            "price": float,
            "extended_price": float,
            "vendor": str,
            "pit": str,
            "material": str,
            "truck": str,
            "trailer_1": str,
            "trailer_2": str,
            "qty": float,
            "units": str,
            "driver": str,
            "notes": str,
        },
        # Composite natural key. 4% of rows have NULL Ticket and will be
        # dropped by _drop_null_dedupe — flagged in ingest_report.md.
        dedupe_keys=["tenant_id", "ticket_date", "ticket", "truck"],
    )
)
