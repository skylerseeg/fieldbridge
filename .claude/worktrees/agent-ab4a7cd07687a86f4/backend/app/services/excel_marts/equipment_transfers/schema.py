"""equipment_transfers — tool/consumable transfer ledger.

Source: Transfer Records.xlsx
Vista v2: emwo
Dedupe: (tenant_id, id) — 'Id' is a clean non-null integer primary key.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.services.excel_marts._base import (
    Column, DateTime, Float, Index, Integer, String, mart,
)

TABLE_NAME = "mart_equipment_transfers"

table = mart(
    TABLE_NAME,
    Column("id", Integer, primary_key=True, nullable=False),
    Column("transfer_date", DateTime),
    Column("tool_consumable", String(300)),
    Column("location", String(200)),
    Column("quantity", Integer),
    Column("total_price", Float),
    Column("requested_by", String(200)),
    Column("user", String(200)),
)

# Status Board needs "latest transfer for tool/consumable X". PK is
# (tenant_id, id) which doesn't help; a tool_consumable+date composite
# does.
Index(
    "ix_mart_equipment_transfers_tenant_tool_transfer",
    table.c.tenant_id,
    table.c.tool_consumable,
    table.c.transfer_date,
)


class EquipmentTransferRow(BaseModel):
    tenant_id: str
    id: int
    transfer_date: datetime | None = None
    tool_consumable: str | None = None
    location: str | None = None
    quantity: int | None = None
    total_price: float | None = None
    requested_by: str | None = None
    user: str | None = None
