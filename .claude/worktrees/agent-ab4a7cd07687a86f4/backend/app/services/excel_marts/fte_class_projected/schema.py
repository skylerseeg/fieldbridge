"""fte_class_projected — FTE projection by craft class, 36 months (Apr 26 – Mar 29).

Source: Job class FTE Projections.xlsx
Vista v2: preh
Dedupe: (tenant_id, class_name).
"""
from __future__ import annotations

from pydantic import BaseModel

from app.services.excel_marts._base import Column, Float, mart
from app.services.excel_marts._fte_shared import (
    MONTHS_26_29, common_identity_columns, month_columns,
)

TABLE_NAME = "mart_fte_class_projected"

table = mart(
    TABLE_NAME,
    *common_identity_columns("class_name"),
    Column("avg_12mo_a", Float),
    *month_columns(MONTHS_26_29[:12]),
    Column("avg_12mo_b", Float),
    *month_columns(MONTHS_26_29[12:24]),
    Column("avg_24mo", Float),
    *month_columns(MONTHS_26_29[24:]),
    Column("avg_36mo", Float),
)


class FteClassProjectedRow(BaseModel):
    tenant_id: str
    class_name: str
    model_config = {"extra": "allow"}
