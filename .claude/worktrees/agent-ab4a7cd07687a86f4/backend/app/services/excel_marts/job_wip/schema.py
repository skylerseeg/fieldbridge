"""job_wip — contract WIP / percent-complete snapshot per job.

Source: WIP report - Job Scheduling.xlsx
Vista v2: jcjm
Dedupe: (tenant_id, contract_job_description) — one row per active contract.
        Rows with null description (~2%) are dropped.
"""
from __future__ import annotations

from pydantic import BaseModel

from app.services.excel_marts._base import Column, Float, String, mart

TABLE_NAME = "mart_job_wip"

table = mart(
    TABLE_NAME,
    Column(
        "contract_job_description", String(300),
        primary_key=True, nullable=False,
    ),
    Column("total_contract", Float),
    Column("contract_cost_td", Float),
    Column("est_cost_to_complete", Float),
    Column("est_total_cost", Float),
    Column("est_gross_profit", Float),
    Column("est_gross_profit_pct", Float),
    Column("percent_complete", Float),
    Column("gain_fade_from_prior_mth", Float),
    Column("billings_to_date", Float),
    Column("over_under_billings", Float),
    Column("contract_revenues_earned", Float),
    Column("gross_profit_loss_td", Float),
    Column("gross_profit_pct_td", Float),
)


class JobWipRow(BaseModel):
    tenant_id: str
    contract_job_description: str
    total_contract: float | None = None
    contract_cost_td: float | None = None
    est_cost_to_complete: float | None = None
    est_total_cost: float | None = None
    est_gross_profit: float | None = None
    est_gross_profit_pct: float | None = None
    percent_complete: float | None = None
    gain_fade_from_prior_mth: float | None = None
    billings_to_date: float | None = None
    over_under_billings: float | None = None
    contract_revenues_earned: float | None = None
    gross_profit_loss_td: float | None = None
    gross_profit_pct_td: float | None = None
