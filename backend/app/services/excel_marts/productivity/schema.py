"""productivity — phase-level hours/units progress, split by resource kind.

Source files:
  - Productivity Summary_labor.xlsx       -> mart_productivity_labor
  - Productivity Summary_equipment.xlsx   -> mart_productivity_equipment

Both source files share an identical column shape (16 columns, sheet
"Productivity Summary"). The only thing that varies between them is the
*meaning* of the hours: labor crew-hours vs. equipment operating hours.

Two parallel tables (rather than one table with a discriminator column)
keeps schema/ingest declarative and avoids needing per-job extra-column
injection in app.core.ingest. The service layer in app.modules.productivity
will UNION ALL these tables with a literal `'labor'`/`'equipment'` column
when the API needs a combined view.

Dedupe / PK: (tenant_id, job_label, phase_label).

Job and phase labels are stored *raw* from the workbook (whitespace-noisy,
e.g. " 2321. - CUWCD Santaquin..."). The service layer applies
_strip_job_key()/_strip_phase_key() at query time — same convention as
mart_estimate_variance and the rest of the FTE marts.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.services.excel_marts._base import (
    Column, DateTime, Float, String, mart,
)

LABOR_TABLE_NAME = "mart_productivity_labor"
EQUIPMENT_TABLE_NAME = "mart_productivity_equipment"


def _build_table(name: str):
    """Factory: emit a productivity Table with the standard column shape.

    Each column maps 1:1 to a source-workbook column (see ingest.COLUMN_MAP).
    Pure SA Core — Base.metadata is shared, so create_all() picks both up.
    """
    return mart(
        name,
        Column("job_label", String(200), primary_key=True, nullable=False),
        Column("phase_label", String(200), primary_key=True, nullable=False),
        # Hours
        Column("actual_hours", Float),
        Column("est_hours", Float),
        Column("variance_hours", Float),       # = est - actual (workbook col)
        Column("percent_used", Float),         # = actual / est
        # Units
        Column("units_complete", Float),
        Column("actual_units", Float),
        Column("percent_complete", Float),     # 0-1 fraction
        # Derived budget / projection
        Column("budget_hours", Float),         # est * %complete
        Column("budget_minus_actual", Float),  # budget - actual
        Column("projected_hours_calc", Float),  # actual / %complete
        Column("projected_hours_pm", Float),    # PM-entered override
        Column("efficiency_rate", Float),
        # Source workbook has a blank-named separator column at index 14
        # (a single space ' ' between Efficiency Rate and End Date). The
        # framework's _rename_columns doesn't drop unmapped columns, so we
        # round-trip it through this nullable sentinel to keep SA Core's
        # _insert(...).values(...) happy. Always NULL in practice.
        Column("_workbook_separator", String(1)),
        Column("project_end_date", DateTime),
    )


labor_table = _build_table(LABOR_TABLE_NAME)
equipment_table = _build_table(EQUIPMENT_TABLE_NAME)


class ProductivityPhaseRow(BaseModel):
    """Single phase row (resource_kind agnostic).

    Used by both tables — the service layer attaches resource_kind when it
    UNION ALLs the two tables for the API surface.
    """
    tenant_id: str
    job_label: str
    phase_label: str
    actual_hours: float | None = None
    est_hours: float | None = None
    variance_hours: float | None = None
    percent_used: float | None = None
    units_complete: float | None = None
    actual_units: float | None = None
    percent_complete: float | None = None
    budget_hours: float | None = None
    budget_minus_actual: float | None = None
    projected_hours_calc: float | None = None
    projected_hours_pm: float | None = None
    efficiency_rate: float | None = None
    project_end_date: datetime | None = None
