"""fte_type_actual — FTE actuals by job type, monthly (Feb 24 – Jan 25).

Source: Job type FTE actual.xlsx
Vista v2: preh
Dedupe: (tenant_id, job_type).
"""
from __future__ import annotations

from pydantic import BaseModel

from app.services.excel_marts._base import Column, Float, mart
from app.services.excel_marts._fte_shared import (
    MONTHS_24_25, common_identity_columns, month_columns,
)

TABLE_NAME = "mart_fte_type_actual"

table = mart(
    TABLE_NAME,
    *common_identity_columns("job_type"),
    Column("avg_12mo_a", Float),
    *month_columns(MONTHS_24_25),
    Column("avg_12mo_b", Float),
)


class FteTypeActualRow(BaseModel):
    tenant_id: str
    job_type: str
    model_config = {"extra": "allow"}
