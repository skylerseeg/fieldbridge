"""hcss_activities IngestJob — HCSS Activities.xlsb."""
from __future__ import annotations

from datetime import datetime

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts.hcss_activities.schema import TABLE_NAME

job = register_job(
    IngestJob(
        name="hcss_activities",
        source_file="HCSS Activities.xlsb",
        target_table=TABLE_NAME,
        sheet_name="HCSS Activities",
        column_map={
            "Estimate Code": "estimate_code",
            "Estimate Name": "estimate_name",
            "Activity Code": "activity_code",
            "Activity Description": "activity_description",
            "Date Created": "date_created",
            "Man Hours": "man_hours",
            "Direct Total Cost": "direct_total_cost",
            "Labor Cost": "labor_cost",
            "Permanent Material Cost": "permanent_material_cost",
            "Construction Material Cost": "construction_material_cost",
            "Equipment Cost": "equipment_cost",
            "Subcontract Cost": "subcontract_cost",
        },
        type_map={
            "estimate_code": str, "estimate_name": str,
            "activity_code": str, "activity_description": str,
            "date_created": datetime,
            "man_hours": float, "direct_total_cost": float,
            "labor_cost": float, "permanent_material_cost": float,
            "construction_material_cost": float,
            "equipment_cost": float, "subcontract_cost": float,
        },
        dedupe_keys=["tenant_id", "estimate_code", "activity_code"],
    )
)
