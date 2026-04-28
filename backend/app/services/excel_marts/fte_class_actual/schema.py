"""fte_class_actual — FTE actuals by craft class, monthly (Feb 24 – Jan 25).

Source: Job class FTE actual projections.xlsx
Vista v2: preh
Dedupe: (tenant_id, class_name).
"""
from __future__ import annotations

from pydantic import BaseModel

from app.services.excel_marts._base import Column, Float, mart
from app.services.excel_marts._fte_shared import (
    MONTHS_24_25, common_identity_columns, month_columns,
)

TABLE_NAME = "mart_fte_class_actual"

table = mart(
    TABLE_NAME,
    *common_identity_columns("class_name"),
    Column("avg_12mo_a", Float),
    *month_columns(MONTHS_24_25),
    Column("avg_12mo_b", Float),
)


class FteClassActualRow(BaseModel):
    tenant_id: str
    class_name: str
    model_config = {"extra": "allow"}
