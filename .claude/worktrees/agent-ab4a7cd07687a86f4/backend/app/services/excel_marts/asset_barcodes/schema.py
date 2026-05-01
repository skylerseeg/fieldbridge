"""asset_barcodes — barcode lookup for tool-room assets.

Source: Barcodes.xlsx
Vista v2: emem
Dedupe: (tenant_id, barcode) — Barcode column is a clean non-null integer PK.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.services.excel_marts._base import (
    Column, DateTime, Integer, String, mart,
)

TABLE_NAME = "mart_asset_barcodes"

table = mart(
    TABLE_NAME,
    Column("barcode", Integer, primary_key=True, nullable=False),
    Column("manufacturer", String(200)),
    Column("material", String(200)),
    Column("model", String(200)),
    Column("retired_date", DateTime),
)


class AssetBarcodeRow(BaseModel):
    tenant_id: str
    barcode: int
    manufacturer: str | None = None
    material: str | None = None
    model: str | None = None
    retired_date: datetime | None = None
