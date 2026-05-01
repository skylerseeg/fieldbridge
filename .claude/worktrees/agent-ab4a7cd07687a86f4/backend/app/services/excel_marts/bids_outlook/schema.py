"""bids_outlook — pipeline of upcoming bids.

Source: Bid Outlook.xlsx
Dedupe: (tenant_id, job, owner, bid_type) — no ID; bid_date has 33% null so
        it can't anchor. Composite keeps entries unique.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.services.excel_marts._base import (
    Boolean, Column, DateTime, Integer, String, Text, mart,
)

TABLE_NAME = "mart_bids_outlook"

table = mart(
    TABLE_NAME,
    Column("job", String(300), primary_key=True, nullable=False),
    Column("owner", String(200), primary_key=True, nullable=False),
    Column("bid_type", String(120), primary_key=True, nullable=False),
    Column("need_plans", Boolean),
    Column("bid_bond", String(120)),
    Column("pq", Boolean),
    Column("sd", Boolean),
    Column("cm_gc", Boolean),
    Column("plan_source", String(120)),
    Column("delivery_type", String(120)),
    Column("public_opening", Boolean),
    Column("completion_date", DateTime),
    Column("engineer_estimate", String(120)),
    Column("ready_for_review", Boolean),
    Column("estimator_time_off", String(200)),
    Column("estimator_name", String(120)),
    Column("bid_date", DateTime),
    Column("anticipated_bid_date", DateTime),
    Column("pre_bid_date", DateTime),
    Column("pre_bid_competitors", Text),
    Column("mandatory", Boolean),
    Column("person_going", String(200)),
    Column("labor_fade_gain", Integer),
    Column("costs_fade_gain", Integer),
    Column("db_wages", Boolean),
    Column("ais", Boolean),
    Column("notes", Text),
)


class BidOutlookRow(BaseModel):
    tenant_id: str
    job: str
    owner: str
    bid_type: str
    model_config = {"extra": "allow"}
