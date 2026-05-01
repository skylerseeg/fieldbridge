"""hcss_activities — HCSS estimate activity line items.

Source: HCSS Activities.xlsb
Dedupe: (tenant_id, estimate_code, activity_code) composite.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.services.excel_marts._base import (
    Column, DateTime, Float, String, Text, mart,
)

TABLE_NAME = "mart_hcss_activities"

table = mart(
    TABLE_NAME,
    Column("estimate_code", String(40), primary_key=True, nullable=False),
    Column("activity_code", String(40), primary_key=True, nullable=False),
    Column("estimate_name", String(200)),
    Column("activity_description", Text),
    Column("date_created", DateTime),
    Column("man_hours", Float),
    Column("direct_total_cost", Float),
    Column("labor_cost", Float),
    Column("permanent_material_cost", Float),
    Column("construction_material_cost", Float),
    Column("equipment_cost", Float),
    Column("subcontract_cost", Float),
)


class HcssActivityRow(BaseModel):
    tenant_id: str
    estimate_code: str
    activity_code: str
    estimate_name: str | None = None
    activity_description: str | None = None
    date_created: datetime | None = None
    man_hours: float | None = None
    direct_total_cost: float | None = None
    labor_cost: float | None = None
    permanent_material_cost: float | None = None
    construction_material_cost: float | None = None
    equipment_cost: float | None = None
    subcontract_cost: float | None = None
