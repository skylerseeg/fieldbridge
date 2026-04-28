"""estimate_variance — estimate vs actual by job and close month.

Source: Estimate Vs Actual.xlsx
Vista v2: jcjm
Dedupe: (tenant_id, job_grouping, close_month) composite natural key.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.services.excel_marts._base import Column, DateTime, Float, String, mart

TABLE_NAME = "mart_estimate_variance"

table = mart(
    TABLE_NAME,
    Column("job_grouping", String(200), primary_key=True, nullable=False),
    Column("close_month", DateTime, primary_key=True, nullable=False),
    Column("estimate", Float),
    Column("actual", Float),
    Column("variance", Float),
    Column("percent", Float),
)


class EstimateVarianceRow(BaseModel):
    tenant_id: str
    job_grouping: str
    close_month: datetime
    estimate: float | None = None
    actual: float | None = None
    variance: float | None = None
    percent: float | None = None
