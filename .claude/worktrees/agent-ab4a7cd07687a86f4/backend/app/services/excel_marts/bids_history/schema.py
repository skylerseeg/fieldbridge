"""bids_history — denormalized bid log (wide competitor columns).

Source: All Bid History.xlsx
Dedupe: (tenant_id, job, bid_date). 'Heavy Bid #' is all zeros in the sample
        so we don't rely on it as a key. Flag for review when full data lands.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.services.excel_marts._base import (
    Boolean, Column, DateTime, Float, Integer, String, Text, mart,
)

TABLE_NAME = "mart_bids_history"


def _wide_bid_cols() -> list[Column]:
    cols: list[Column] = []
    for i in range(1, 18):
        cols.append(Column(f"bid_{i}_comp", String(200)))
        cols.append(Column(f"bid_{i}_amt", Float))
        cols.append(Column(f"bid_{i}_won", Float))
    return cols


table = mart(
    TABLE_NAME,
    Column("job", String(300), primary_key=True, nullable=False),
    Column("bid_date", DateTime, primary_key=True, nullable=False),
    Column("was_bid", Boolean),
    Column("heavy_bid_number", Integer),
    Column("owner", String(200)),
    Column("bid_type", String(120)),
    Column("county", String(120)),
    Column("estimator", String(120)),
    Column("completion_date", DateTime),
    Column("labor_cost_factor", Float),
    Column("avg_mark_up_pct", Float),
    Column("mark_up", Float),
    Column("overhead_add_on", Float),
    Column("equip_op_exp", Float),
    Column("co_equip", Float),
    Column("high", Float),
    Column("low", Float),
    Column("vancon", Float),
    Column("rank", Float),
    Column("won", Float),
    Column("lost_by", Float),
    Column("percent_over", Float),
    Column("number_bidders", Float),
    Column("bids", Text),
    Column("pq", Boolean),
    Column("plan_source", String(120)),
    Column("db_wages", Boolean),
    Column("engineer_estimate", String(120)),
    Column("notice_to_proceed_date", DateTime),
    Column("competitor_ids", Text),
    Column("deep", Float),
    Column("traffic_control", Float),
    Column("dewatering", Float),
    Column("bypass_pumping", Float),
    Column("tight_time_frame", Float),
    Column("tight_job_site", Float),
    Column("haul_off", Float),
    Column("insurance_requirement", Float),
    *_wide_bid_cols(),
)


class BidHistoryRow(BaseModel):
    tenant_id: str
    job: str
    bid_date: datetime
    # Dozens of optional floats/strs omitted for brevity — all nullable,
    # mirror the Column list above.
    model_config = {"extra": "allow"}
