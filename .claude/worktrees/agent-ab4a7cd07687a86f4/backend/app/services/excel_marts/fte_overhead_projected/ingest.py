"""fte_overhead_projected IngestJob — Overhead FTE Projections.xlsx."""
from __future__ import annotations

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts._fte_shared import (
    MONTHS_24_25, month_column_map, month_type_map,
)
from app.services.excel_marts.fte_overhead_projected.schema import TABLE_NAME


def _column_map() -> dict[str, str]:
    m = {
        "Department": "department",
        "Code": "code",
        "Craft/Class": "craft_class",
        "Monthly Hours": "monthly_hours",
        "Last Month Actuals": "last_month_actuals",
        "12-Month Avg Totals": "avg_12mo_a",
        "12-Month Avg Totals.1": "avg_12mo_b",
    }
    m.update(month_column_map(MONTHS_24_25))
    return m


def _type_map() -> dict[str, type]:
    t: dict[str, type] = {
        "department": str, "code": str, "craft_class": str,
        "monthly_hours": float, "last_month_actuals": float,
        "avg_12mo_a": float, "avg_12mo_b": float,
    }
    t.update(month_type_map(MONTHS_24_25))
    return t


job = register_job(
    IngestJob(
        name="fte_overhead_projected",
        source_file="Overhead FTE Projections.xlsx",
        target_table=TABLE_NAME,
        sheet_name="FTE Projections",
        column_map=_column_map(),
        type_map=_type_map(),
        dedupe_keys=["tenant_id", "department"],
    )
)
