"""estimate_variance IngestJob — Estimate Vs Actual.xlsx."""
from __future__ import annotations

from datetime import datetime

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts.estimate_variance.schema import TABLE_NAME

job = register_job(
    IngestJob(
        name="estimate_variance",
        source_file="Estimate Vs Actual.xlsx",
        target_table=TABLE_NAME,
        sheet_name="Estimate Vs Actual",
        column_map={
            "Job / Grouping": "job_grouping",
            "Close Month": "close_month",
            "Estimate": "estimate",
            "Actual": "actual",
            "Variance": "variance",
            "Percent": "percent",
        },
        type_map={
            "job_grouping": str, "close_month": datetime,
            "estimate": float, "actual": float,
            "variance": float, "percent": float,
        },
        dedupe_keys=["tenant_id", "job_grouping", "close_month"],
    )
)
