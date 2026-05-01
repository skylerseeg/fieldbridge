"""hours_projected — projected labor hours by job + phase, wide-quarterly.

Source: Projected Hours.xlsx
Vista v2: preh
Dedupe: (tenant_id, job, phase) composite. Phase combined with job is
        unique per sample.
"""
from __future__ import annotations

from pydantic import BaseModel

from app.services.excel_marts._base import Column, Float, String, mart

TABLE_NAME = "mart_hours_projected"

_QUARTERS = [
    ("mar_26_partial", "Mar – Mar '26"),
    ("q_apr_jun_26", "Apr – Jun '26"),
    ("q_jul_sep_26", "Jul – Sep '26"),
    ("q_oct_dec_26", "Oct – Dec '26"),
    ("total_2026", "2026 Totals"),
    ("q_jan_mar_27", "Jan – Mar '27"),
    ("q_apr_jun_27", "Apr – Jun '27"),
    ("q_jul_sep_27", "Jul – Sep '27"),
    ("q_oct_dec_27", "Oct – Dec '27"),
    ("total_2027", "2027 Totals"),
    ("q_jan_mar_28", "Jan – Mar '28"),
    ("q_apr_jun_28", "Apr – Jun '28"),
    ("q_jul_sep_28", "Jul – Sep '28"),
    ("q_oct_dec_28", "Oct – Dec '28"),
    ("total_2028", "2028 Totals"),
    ("q_jan_mar_29", "Jan – Mar '29"),
    ("q_apr_jun_29", "Apr – Jun '29"),
    ("q_jul_sep_29", "Jul – Sep '29"),
    ("q_oct_dec_29", "Oct – Dec '29"),
    ("total_2029", "2029 Totals"),
]

QUARTER_COL_MAP: dict[str, str] = {src: tgt for tgt, src in _QUARTERS}


table = mart(
    TABLE_NAME,
    Column("job", String(300), primary_key=True, nullable=False),
    Column("phase", String(120), primary_key=True, nullable=False),
    Column("phase_master", String(120)),
    Column("pr_dept", String(80)),
    Column("actual_hours", Float),
    Column("progress_pct_complete", Float),
    Column("current_estimated_hours", Float),
    Column("projected_hours_remaining", Float),
    Column("projected_hours_allocated", Float),
    Column("projected_hours_unallocated", Float),
    Column("workoff_start", Float),
    Column("workoff_comp", Float),
    *[Column(tgt, Float) for tgt, _ in _QUARTERS],
)


class HoursProjectedRow(BaseModel):
    tenant_id: str
    job: str
    phase: str
    model_config = {"extra": "allow"}
