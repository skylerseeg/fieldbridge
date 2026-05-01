"""proposals — thin proposal-bid headers (4 cols).

Source: Proposal Bids.xlsx
Dedupe: (tenant_id, job, owner, bid_type) — all 4 source cols are
        non-null in the sample, so use all-but-county as the composite key.
"""
from __future__ import annotations

from pydantic import BaseModel

from app.services.excel_marts._base import Column, String, mart

TABLE_NAME = "mart_proposals"

table = mart(
    TABLE_NAME,
    Column("job", String(300), primary_key=True, nullable=False),
    Column("owner", String(200), primary_key=True, nullable=False),
    Column("bid_type", String(120), primary_key=True, nullable=False),
    Column("county", String(120)),
)


class ProposalRow(BaseModel):
    tenant_id: str
    job: str
    owner: str
    bid_type: str
    county: str | None = None
