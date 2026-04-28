"""employee_assets — assets issued to employees.

Source: Employee Assets.xlsx
Vista v2: emem
Dedupe: (tenant_id, asset) — Asset column is unique per row in the sample.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.services.excel_marts._base import (
    Boolean, Column, DateTime, Integer, String, Text, mart,
)

TABLE_NAME = "mart_employee_assets"

table = mart(
    TABLE_NAME,
    Column("asset", String(120), primary_key=True, nullable=False),
    Column("description", String(400)),
    Column("category", String(80)),
    Column("device", String(80)),
    Column("identifier", String(200)),
    Column("os_install", DateTime),
    Column("unassigned_location", String(120)),
    Column("employee", String(200)),
    Column("employee_active", Boolean),
    Column("hr_ref", Integer),
    Column("on_truck", String(120)),
    Column("date_out", DateTime),
    Column("memo_out", Text),
)


class EmployeeAssetRow(BaseModel):
    tenant_id: str
    asset: str
    description: str | None = None
    category: str | None = None
    device: str | None = None
    identifier: str | None = None
    os_install: datetime | None = None
    unassigned_location: str | None = None
    employee: str | None = None
    employee_active: bool | None = None
    hr_ref: int | None = None
    on_truck: str | None = None
    date_out: datetime | None = None
    memo_out: str | None = None
