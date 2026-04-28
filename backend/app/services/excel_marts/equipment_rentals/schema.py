"""equipment_rentals — outside rental equipment on jobs.

Source: Rentals.xlsx
Vista v2: apvend (for vendor dim), emwo (for rental assignments)
Dedupe: (tenant_id, equipment, rental_company, picked_up_date) composite.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.services.excel_marts._base import (
    Boolean, Column, DateTime, Float, Index, String, mart,
)

TABLE_NAME = "mart_equipment_rentals"

table = mart(
    TABLE_NAME,
    Column("equipment", String(200), primary_key=True, nullable=False),
    Column("rental_company", String(200), primary_key=True, nullable=False),
    Column("picked_up_date", DateTime, primary_key=True, nullable=False),
    Column("images", String(40)),
    Column("job", String(200)),
    Column("rented_by", String(200)),
    Column("picked_up_by", String(200)),
    Column("scheduled_return_date", DateTime),
    Column("returned_date", DateTime),
    Column("maintained_by", Boolean),
    Column("rental_length", String(80)),
    Column("rate", Float),
    Column("rate_unit", String(40)),
    Column("hours_start", Float),
    Column("hours_end", Float),
    Column("serial_number", String(120)),
    Column("is_rpo", Boolean),
)

# Status Board path: "rentals for equipment X within date range Y..Z".
# The PK is (tenant_id, equipment, rental_company, picked_up_date), so
# rental_company sits between equipment and the date — preventing the PK
# from serving range scans without a company filter. This composite skips
# rental_company and gives the read path a direct (tenant, equipment, date)
# walk.
Index(
    "ix_mart_equipment_rentals_tenant_equipment_picked_up",
    table.c.tenant_id,
    table.c.equipment,
    table.c.picked_up_date,
)


class EquipmentRentalRow(BaseModel):
    tenant_id: str
    equipment: str
    rental_company: str
    picked_up_date: datetime
    images: str | None = None
    job: str | None = None
    rented_by: str | None = None
    picked_up_by: str | None = None
    scheduled_return_date: datetime | None = None
    returned_date: datetime | None = None
    maintained_by: bool | None = None
    rental_length: str | None = None
    rate: float | None = None
    rate_unit: str | None = None
    hours_start: float | None = None
    hours_end: float | None = None
    serial_number: str | None = None
    is_rpo: bool | None = None
