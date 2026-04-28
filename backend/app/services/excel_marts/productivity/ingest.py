"""productivity IngestJob registrations.

Two jobs, identical column_map / type_map / dedupe_keys, different source
files and target tables:

    productivity.labor       Productivity Summary_labor.xlsx     -> mart_productivity_labor
    productivity.equipment   Productivity Summary_equipment.xlsx -> mart_productivity_equipment

The two source files share the same Productivity Summary sheet shape.
The blank-named column at the source's index 14 (' ') is mapped to a
sentinel column (`_workbook_separator`) on the mart tables — the
framework's `_rename_columns` does NOT drop unmapped columns, and
SA Core's `_insert(table).values(chunk)` raises CompileError on
unconsumed keys. Round-tripping the blank column through a nullable
sentinel column is the cheapest workaround.
"""
from __future__ import annotations

from datetime import datetime

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts.productivity.schema import (
    EQUIPMENT_TABLE_NAME,
    LABOR_TABLE_NAME,
)

SHEET_NAME = "Productivity Summary"

COLUMN_MAP = {
    "Job": "job_label",
    "Phase": "phase_label",
    "Actual Hours": "actual_hours",
    "Est Hours": "est_hours",
    "Variance": "variance_hours",
    "Percent Used": "percent_used",
    "Units Complete": "units_complete",
    "Actual Units": "actual_units",
    "% Complete": "percent_complete",
    "Calculated Budget Hrs": "budget_hours",
    "Calculated Budget Hrs-Actual": "budget_minus_actual",
    "Calculated Projected Hours": "projected_hours_calc",
    "Projected Hours": "projected_hours_pm",
    "Efficiency Rate": "efficiency_rate",
    # Blank-named separator column in the source workbook (single space).
    # See schema.py for the _workbook_separator note.
    " ": "_workbook_separator",
    "End Date": "project_end_date",
}

TYPE_MAP = {
    "job_label": str,
    "phase_label": str,
    "actual_hours": float,
    "est_hours": float,
    "variance_hours": float,
    "percent_used": float,
    "units_complete": float,
    "actual_units": float,
    "percent_complete": float,
    "budget_hours": float,
    "budget_minus_actual": float,
    "projected_hours_calc": float,
    "projected_hours_pm": float,
    "efficiency_rate": float,
    "project_end_date": datetime,
}

DEDUPE_KEYS = ["tenant_id", "job_label", "phase_label"]


labor_job = register_job(
    IngestJob(
        name="productivity.labor",
        source_file="Productivity Summary_labor.xlsx",
        target_table=LABOR_TABLE_NAME,
        sheet_name=SHEET_NAME,
        column_map=COLUMN_MAP,
        type_map=TYPE_MAP,
        dedupe_keys=DEDUPE_KEYS,
    )
)


equipment_job = register_job(
    IngestJob(
        name="productivity.equipment",
        source_file="Productivity Summary_equipment.xlsx",
        target_table=EQUIPMENT_TABLE_NAME,
        sheet_name=SHEET_NAME,
        column_map=COLUMN_MAP,
        type_map=TYPE_MAP,
        dedupe_keys=DEDUPE_KEYS,
    )
)
