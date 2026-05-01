"""equipment_fuel — material/fuel totals by job.

Source: Material analytics Fuel Totals.xlsx
Vista v2: emem
Dedupe: (tenant_id, job, job_type) composite.
"""
from __future__ import annotations

from pydantic import BaseModel

from app.services.excel_marts._base import Column, Float, Integer, String, mart

TABLE_NAME = "mart_equipment_fuel"

table = mart(
    TABLE_NAME,
    Column("job", String(200), primary_key=True, nullable=False),
    Column("job_type", String(80), primary_key=True, nullable=False),
    Column("material_tons", Float),
    Column("concrete_yards", Integer),
    Column("flowfill_yards", Integer),
)


class EquipmentFuelRow(BaseModel):
    tenant_id: str
    job: str
    job_type: str
    material_tons: float | None = None
    concrete_yards: int | None = None
    flowfill_yards: int | None = None
