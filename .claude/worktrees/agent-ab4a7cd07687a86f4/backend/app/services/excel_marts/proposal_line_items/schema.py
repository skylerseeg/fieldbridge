"""proposal_line_items — per-proposal competitor line detail.

Source: Proposal Bid Details.xlsx
Dedupe: _row_hash — only 1 row sampled, no unique key apparent yet.
        Promote to (proposal_id, competitor) once data volume grows.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.services.excel_marts._base import (
    Column, DateTime, Float, Integer, String, mart, row_hash_col,
)

TABLE_NAME = "mart_proposal_line_items"

table = mart(
    TABLE_NAME,
    row_hash_col(),
    Column("competitor", String(200)),
    Column("design_fee", Integer),
    Column("cm_fee", Integer),
    Column("cm_monthly_fee", Integer),
    Column("contractor_ohp_fee", Integer),
    Column("contractor_bonds_ins", Integer),
    Column("contractor_co_markup", Integer),
    Column("city_budget", Integer),
    Column("contractor_start", DateTime),
    Column("contractor_days", Integer),
    Column("contractor_projects", Integer),
    Column("pm_projects", Integer),
    Column("contractor_pm", String(200)),
    Column("contractor_super", String(200)),
    Column("reference_1", String(200)),
    Column("reference_2", String(200)),
    Column("reference_3", String(200)),
)


class ProposalLineItemRow(BaseModel):
    tenant_id: str
    competitor: str | None = None
    design_fee: int | None = None
    cm_fee: int | None = None
    cm_monthly_fee: int | None = None
    contractor_ohp_fee: int | None = None
    contractor_bonds_ins: int | None = None
    contractor_co_markup: int | None = None
    city_budget: int | None = None
    contractor_start: datetime | None = None
    contractor_days: int | None = None
    contractor_projects: int | None = None
    pm_projects: int | None = None
    contractor_pm: str | None = None
    contractor_super: str | None = None
    reference_1: str | None = None
    reference_2: str | None = None
    reference_3: str | None = None
