"""work_orders — equipment work order table.

Source: none (no Excel sheet for WOs).
Vista v2: emwo — 1:1 column match except for the two planning fields
(``estimated_cost``, ``estimated_hours``) that Vista stores in an
adjacent ``emwoest``-style table. The mart keeps them inline so
``cost_to_date vs budget`` is a single aggregate.

Dedupe: (tenant_id, work_order) — WO number is the natural key.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.services.excel_marts._base import (
    Column, DateTime, Float, Index, String, Text, mart,
)

TABLE_NAME = "mart_work_orders"

table = mart(
    TABLE_NAME,
    Column("work_order", String(40), primary_key=True, nullable=False),
    Column("equipment", String(40)),
    Column("description", Text),
    Column("status", String(10)),            # O=Open, C=Closed, H=Hold
    Column("priority", String(10)),          # 1=Critical, 2=High, 3=Normal
    Column("requested_by", String(80)),
    Column("open_date", DateTime),
    Column("closed_date", DateTime),
    Column("mechanic", String(40)),
    Column("labor_hours", Float),
    Column("parts_cost", Float),
    Column("total_cost", Float),
    Column("job_number", String(40)),
    # Planning fields — inline in the mart; sourced from Vista emwoest v2.
    Column("estimated_hours", Float),
    Column("estimated_cost", Float),
)

# WO module's overdue/aging queries AND the Equipment Status Board's
# "open WO for asset X" join both lead with (tenant, equipment, status).
# Adding open_date as the trailing column lets aging/recency filters
# use the same index.
Index(
    "ix_mart_work_orders_tenant_equipment_status_open",
    table.c.tenant_id,
    table.c.equipment,
    table.c.status,
    table.c.open_date,
)


class WorkOrderRow(BaseModel):
    tenant_id: str
    work_order: str
    equipment: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    requested_by: str | None = None
    open_date: datetime | None = None
    closed_date: datetime | None = None
    mechanic: str | None = None
    labor_hours: float | None = None
    parts_cost: float | None = None
    total_cost: float | None = None
    job_number: str | None = None
    estimated_hours: float | None = None
    estimated_cost: float | None = None
