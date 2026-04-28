"""hours_projected IngestJob — Projected Hours.xlsx.

Source has Unicode em-dash (–) in quarterly column headers — preserved in
the column_map verbatim, mapped to ASCII snake_case in the DB.
"""
from __future__ import annotations

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts.hours_projected.schema import (
    QUARTER_COL_MAP, TABLE_NAME,
)


def _column_map() -> dict[str, str]:
    m = {
        "Job": "job",
        "Phase": "phase",
        "Phase Master": "phase_master",
        "PR Dept": "pr_dept",
        "Actual Hours": "actual_hours",
        "Progress % Complete": "progress_pct_complete",
        "Current Estimated Hours": "current_estimated_hours",
        "Projected Hours Remaining": "projected_hours_remaining",
        "Projected Hours Allocated": "projected_hours_allocated",
        "Projected Hours Unallocated": "projected_hours_unallocated",
        "Workoff Start": "workoff_start",
        "Workoff Comp": "workoff_comp",
    }
    m.update(QUARTER_COL_MAP)
    return m


def _type_map() -> dict[str, type]:
    t: dict[str, type] = {
        "job": str, "phase": str, "phase_master": str, "pr_dept": str,
        "actual_hours": float, "progress_pct_complete": float,
        "current_estimated_hours": float,
        "projected_hours_remaining": float,
        "projected_hours_allocated": float,
        "projected_hours_unallocated": float,
        "workoff_start": float, "workoff_comp": float,
    }
    for tgt in QUARTER_COL_MAP.values():
        t[tgt] = float
    return t


job = register_job(
    IngestJob(
        name="hours_projected",
        source_file="Projected Hours.xlsx",
        target_table=TABLE_NAME,
        sheet_name="Projected Hours",
        column_map=_column_map(),
        type_map=_type_map(),
        dedupe_keys=["tenant_id", "job", "phase"],
    )
)
