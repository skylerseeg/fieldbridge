"""equipment_rentals IngestJob — Rentals.xlsx.

Small sample (4 rows) — dedupe key verified against name-company-date
triples rather than a machine-issued ID that isn't present.
"""
from __future__ import annotations

from datetime import datetime

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts.equipment_rentals.schema import TABLE_NAME

job = register_job(
    IngestJob(
        name="equipment_rentals",
        source_file="Rentals.xlsx",
        target_table=TABLE_NAME,
        sheet_name="Rentals",
        column_map={
            "Equipment": "equipment",
            "Images": "images",
            "Rental Company": "rental_company",
            "Job": "job",
            "Rented By": "rented_by",
            "Picked Up By": "picked_up_by",
            "Picked Up Date": "picked_up_date",
            "Scheduled Return Date": "scheduled_return_date",
            "Returned Date": "returned_date",
            "Maintained By": "maintained_by",
            "Rental Length": "rental_length",
            "Rate": "rate",
            "Rate Unit": "rate_unit",
            "Hours Start": "hours_start",
            "Hours End": "hours_end",
            "Serial Number": "serial_number",
            "Is RPO": "is_rpo",
        },
        type_map={
            "equipment": str, "images": str, "rental_company": str,
            "job": str, "rented_by": str, "picked_up_by": str,
            "picked_up_date": datetime,
            "scheduled_return_date": datetime, "returned_date": datetime,
            "maintained_by": bool, "rental_length": str,
            "rate": float, "rate_unit": str,
            "hours_start": float, "hours_end": float,
            "serial_number": str, "is_rpo": bool,
        },
        dedupe_keys=[
            "tenant_id", "equipment", "rental_company", "picked_up_date",
        ],
    )
)
