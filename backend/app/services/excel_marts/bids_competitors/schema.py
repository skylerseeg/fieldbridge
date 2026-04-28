"""bids_competitors — per-job competitor bid roster.

Source: Competitor Bids.xlsx
Dedupe: (tenant_id, job, heavy_bid_number, bid_date) composite.
Note: source file has 0 data rows in the current export; schema is built
from headers only. Flagged in ingest_report.md.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.services.excel_marts._base import (
    Column, DateTime, Float, Integer, String, mart,
)

TABLE_NAME = "mart_bids_competitors"

table = mart(
    TABLE_NAME,
    Column("job", String(300), primary_key=True, nullable=False),
    Column("heavy_bid_number", String(40), primary_key=True, nullable=False),
    Column("bid_date", DateTime, primary_key=True, nullable=False),
    Column("bid_type", String(120)),
    Column("bid_amount", Float),
    Column("rank", Integer),
    Column("won", String(20)),
    Column("num_bidders", Integer),
    Column("low", Float),
    Column("high", Float),
    Column("vancon", Float),
    Column("lower_than_vancon", Float),
)


class BidCompetitorRow(BaseModel):
    tenant_id: str
    job: str
    heavy_bid_number: str
    bid_date: datetime
    bid_type: str | None = None
    bid_amount: float | None = None
    rank: int | None = None
    won: str | None = None
    num_bidders: int | None = None
    low: float | None = None
    high: float | None = None
    vancon: float | None = None
    lower_than_vancon: float | None = None
