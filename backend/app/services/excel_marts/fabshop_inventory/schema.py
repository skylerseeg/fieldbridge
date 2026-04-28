"""fabshop_inventory — fab-shop stock list.

Source: FabShopStockProducts.xlsx
Dedupe: (tenant_id, description) — product description appears to be
        unique per row in the 38-row sample. If duplicates show up, UPSERT
        will update the price.
"""
from __future__ import annotations

from pydantic import BaseModel

from app.services.excel_marts._base import Column, Integer, String, mart

TABLE_NAME = "mart_fabshop_inventory"

table = mart(
    TABLE_NAME,
    Column("description", String(400), primary_key=True, nullable=False),
    Column("price", Integer),
)


class FabshopInventoryRow(BaseModel):
    tenant_id: str
    description: str
    price: int | None = None
