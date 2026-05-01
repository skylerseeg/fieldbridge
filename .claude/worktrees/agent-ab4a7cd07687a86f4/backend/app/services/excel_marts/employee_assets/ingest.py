"""employee_assets IngestJob — Employee Assets.xlsx.

Note: source header 'Unassiged Location' is a typo in the Excel file; we
normalize to 'unassigned_location' in the mart.
"""
from __future__ import annotations

from datetime import datetime

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts.employee_assets.schema import TABLE_NAME

job = register_job(
    IngestJob(
        name="employee_assets",
        source_file="Employee Assets.xlsx",
        target_table=TABLE_NAME,
        sheet_name="Employee Assets",
        column_map={
            "Asset": "asset",
            "Description": "description",
            "Category": "category",
            "Device": "device",
            "Identifier": "identifier",
            "OS Install": "os_install",
            "Unassiged Location": "unassigned_location",
            "Employee": "employee",
            "Employee Active": "employee_active",
            "HrRef": "hr_ref",
            "On Truck": "on_truck",
            "Date Out": "date_out",
            "Memo Out": "memo_out",
        },
        type_map={
            "asset": str, "description": str, "category": str,
            "device": str, "identifier": str,
            "os_install": datetime, "date_out": datetime,
            "unassigned_location": str, "employee": str,
            "employee_active": bool, "hr_ref": int,
            "on_truck": str, "memo_out": str,
        },
        dedupe_keys=["tenant_id", "asset"],
    )
)
