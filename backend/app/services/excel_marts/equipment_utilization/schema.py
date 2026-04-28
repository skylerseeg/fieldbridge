"""equipment_utilization — haul-ticket / utilization log.

Source: Equipment Utilization.xlsx
Vista v2: emem + emwo
Dedupe: composite natural key (ticket_date, ticket, truck)
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.services.excel_marts._base import (
    Boolean, Column, DateTime, Float, Index, String, Text, mart,
)

TABLE_NAME = "mart_equipment_utilization"

table = mart(
    TABLE_NAME,
    Column("ticket_date", DateTime, primary_key=True, nullable=False),
    Column("ticket", String(40), primary_key=True, nullable=False),
    Column("truck", String(80), primary_key=True, nullable=False),
    Column("job", String(200)),
    Column("images", Text),
    Column("is_lessor", Boolean),
    Column("invoiced", Boolean),
    Column("invoice_number", String(80)),
    Column("invoice_date", DateTime),
    Column("price", Float),
    Column("extended_price", Float),
    Column("vendor", String(200)),
    Column("pit", String(200)),
    Column("material", String(120)),
    Column("trailer_1", String(80)),
    Column("trailer_2", String(80)),
    Column("qty", Float),
    Column("units", String(40)),
    Column("driver", String(120)),
    Column("notes", Text),
)

# Equipment Status Board / list-by-truck access pattern. The PK leads on
# ticket_date so queries that filter by truck first can't use it. This
# composite gives the read path a tenant-scoped truck-history index.
Index(
    "ix_mart_equipment_utilization_tenant_truck_ticket_date",
    table.c.tenant_id,
    table.c.truck,
    table.c.ticket_date,
)


class EquipmentUtilizationRow(BaseModel):
    tenant_id: str
    ticket_date: datetime
    ticket: str
    truck: str
    job: str | None = None
    images: str | None = None
    is_lessor: bool | None = None
    invoiced: bool | None = None
    invoice_number: str | None = None
    invoice_date: datetime | None = None
    price: float | None = None
    extended_price: float | None = None
    vendor: str | None = None
    pit: str | None = None
    material: str | None = None
    trailer_1: str | None = None
    trailer_2: str | None = None
    qty: float | None = None
    units: str | None = None
    driver: str | None = None
    notes: str | None = None
