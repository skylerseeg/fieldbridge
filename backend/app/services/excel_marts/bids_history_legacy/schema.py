"""bids_history_legacy — older/thinner bid log.

Source: Bid History.xlsx
Dedupe: (tenant_id, job, bid_date) composite — matches bids_history.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.services.excel_marts._base import (
    Boolean, Column, DateTime, Float, Integer, String, Text, mart,
)

TABLE_NAME = "mart_bids_history_legacy"

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
    Column("abstracts", Float),
    Column("labor_cost_factor", Float),
    Column("avg_mark_up_pct", Float),
    Column("mark_up", Float),
    Column("overhead_add_on", Float),
    Column("equip_op_exp", Float),
    Column("co_equip", Float),
    Column("high", Float),
    Column("low", Float),
    Column("won", Float),
    Column("vancon", Float),
    Column("rank", Float),
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
)


class BidHistoryLegacyRow(BaseModel):
    tenant_id: str
    job: str
    bid_date: datetime
    model_config = {"extra": "allow"}
