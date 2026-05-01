"""estimates — HCSS estimate headers.

Source: Estimates.xlsx
Vista v2: jcjm
Dedupe: (tenant_id, code) — HCSS estimate code is the natural PK.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.services.excel_marts._base import Column, DateTime, Float, Integer, String, mart

TABLE_NAME = "mart_estimates"

table = mart(
    TABLE_NAME,
    Column("code", String(40), primary_key=True, nullable=False),
    Column("name", String(200)),
    Column("date_created", DateTime),
    Column("estimate_total_cost", Float),
    Column("actual_bid_markup", Float),
    Column("actual_markup_takeoff", Float),
    Column("addon_bond_total", Float),
    Column("addon_cost", Float),
    Column("bond_total", Float),
    Column("addon_markup", Integer),
    Column("bid_date", DateTime),
    Column("bid_total", Float),
    Column("overhead_pct", Float),
)


class EstimateRow(BaseModel):
    tenant_id: str
    code: str
    name: str | None = None
    date_created: datetime | None = None
    estimate_total_cost: float | None = None
    actual_bid_markup: float | None = None
    actual_markup_takeoff: float | None = None
    addon_bond_total: float | None = None
    addon_cost: float | None = None
    bond_total: float | None = None
    addon_markup: int | None = None
    bid_date: datetime | None = None
    bid_total: float | None = None
    overhead_pct: float | None = None
