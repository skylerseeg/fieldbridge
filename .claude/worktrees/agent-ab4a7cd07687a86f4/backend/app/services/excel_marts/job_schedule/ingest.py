"""job_schedule IngestJob — Job Scheduling.xlsx.

Source column 'Proj End' shows up as float in pandas introspection; treated
as datetime here — coerce-errors will null bad cells and flag in errors.
"""
from __future__ import annotations

from datetime import datetime

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts.job_schedule.schema import TABLE_NAME

job = register_job(
    IngestJob(
        name="job_schedule",
        source_file="Job Scheduling.xlsx",
        target_table=TABLE_NAME,
        sheet_name="Job Scheduling",
        column_map={
            "Priority": "priority",
            "Job": "job",
            "Start": "start",
            "Proj End": "proj_end",
            "Milestone": "milestone",
            "Reason": "reason",
            "Priority Department(s)": "priority_departments",
            "Liquidated Damage": "liquidated_damage",
            "Chad Wants": "chad_wants",
        },
        type_map={
            "priority": int, "job": str,
            "start": datetime, "proj_end": datetime, "milestone": datetime,
            "reason": str, "priority_departments": str,
            "liquidated_damage": float, "chad_wants": float,
        },
        dedupe_keys=["tenant_id", "priority", "job"],
    )
)
