"""vendors — firm/contact directory.

Source: Firm Contacts.xlsx
Vista v2: apvend
Dedupe: _row_hash (no natural key — ~46% null Name, ~82% null Email).
        Flagged as WARN in ingest_log for data-quality review.
"""
from __future__ import annotations

from pydantic import BaseModel

from app.services.excel_marts._base import Column, String, Text, mart, row_hash_col

TABLE_NAME = "mart_vendors"

table = mart(
    TABLE_NAME,
    row_hash_col(),
    Column("name", String(200)),
    Column("firm_type", String(120)),
    Column("contact", String(200)),
    Column("title", String(120)),
    Column("email", String(200)),
    Column("phone", String(40)),
    Column("code_1", String(40)),
    Column("code_2", String(40)),
    Column("code_3", String(40)),
    Column("code_4", String(40)),
    Column("code_5", String(40)),
)


class VendorRow(BaseModel):
    tenant_id: str
    name: str | None = None
    firm_type: str | None = None
    contact: str | None = None
    title: str | None = None
    email: str | None = None
    phone: str | None = None
    code_1: str | None = None
    code_2: str | None = None
    code_3: str | None = None
    code_4: str | None = None
    code_5: str | None = None
