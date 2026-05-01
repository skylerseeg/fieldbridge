"""fte_overhead_actual — overhead FTE actuals by department, monthly.

Source: Overhead FTE Actuals.xlsx
Vista v2: preh
Dedupe: (tenant_id, department).
"""
from __future__ import annotations

from pydantic import BaseModel

from app.services.excel_marts._base import Column, Float, mart
from app.services.excel_marts._fte_shared import (
    MONTHS_24_25, common_identity_columns, month_columns,
)

TABLE_NAME = "mart_fte_overhead_actual"

table = mart(
    TABLE_NAME,
    *common_identity_columns("department"),
    Column("avg_12mo_a", Float),
    *month_columns(MONTHS_24_25),
    Column("avg_12mo_b", Float),
)


class FteOverheadActualRow(BaseModel):
    tenant_id: str
    department: str
    model_config = {"extra": "allow"}
