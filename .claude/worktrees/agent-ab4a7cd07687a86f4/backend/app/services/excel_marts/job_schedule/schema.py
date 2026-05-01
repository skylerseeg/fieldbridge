"""job_schedule — active job schedule ranked by priority.

Source: Job Scheduling.xlsx
Vista v2: jcjm
Dedupe: (tenant_id, priority, job) composite — priority is the rank and job
is the label; combined they're unique per sample.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.services.excel_marts._base import (
    Column, DateTime, Float, Integer, String, Text, mart,
)

TABLE_NAME = "mart_job_schedule"

table = mart(
    TABLE_NAME,
    Column("priority", Integer, primary_key=True, nullable=False),
    Column("job", String(200), primary_key=True, nullable=False),
    Column("start", DateTime),
    Column("proj_end", DateTime),
    Column("milestone", DateTime),
    Column("reason", Text),
    Column("priority_departments", String(200)),
    Column("liquidated_damage", Float),
    Column("chad_wants", Float),
)


class JobScheduleRow(BaseModel):
    tenant_id: str
    priority: int
    job: str
    start: datetime | None = None
    proj_end: datetime | None = None
    milestone: datetime | None = None
    reason: str | None = None
    priority_departments: str | None = None
    liquidated_damage: float | None = None
    chad_wants: float | None = None
