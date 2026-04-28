"""Shared helpers for the FTE family of marts.

All FTE Excel exports use the same wide shape (one row per class / job
type / department × N month columns). Columns vary per file:

  - fte_class_actual / fte_type_actual / fte_overhead_actual / projected
    (19 cols: 12 months + 2 rolling-avg aggregates + identity cols)

  - fte_class_projected
    (45 cols: 36 months + 4 aggregates + identity cols)

Month headers look like 'Feb 24' → 'feb_24' in the DB.
"""
from __future__ import annotations

from app.services.excel_marts._base import Column, Float, String


# Year 2024-02 through 2025-01 (12 months), used by all 19-col FTE files.
MONTHS_24_25 = [
    "Feb 24", "Mar 24", "Apr 24", "May 24", "Jun 24", "Jul 24", "Aug 24",
    "Sep 24", "Oct 24", "Nov 24", "Dec 24", "Jan 25",
]

# Year 2026-04 through 2029-03 (36 months), used by fte_class_projected.
MONTHS_26_29 = [
    "Apr 26", "May 26", "Jun 26", "Jul 26", "Aug 26", "Sep 26",
    "Oct 26", "Nov 26", "Dec 26", "Jan 27", "Feb 27", "Mar 27",
    "Apr 27", "May 27", "Jun 27", "Jul 27", "Aug 27", "Sep 27",
    "Oct 27", "Nov 27", "Dec 27", "Jan 28", "Feb 28", "Mar 28",
    "Apr 28", "May 28", "Jun 28", "Jul 28", "Aug 28", "Sep 28",
    "Oct 28", "Nov 28", "Dec 28", "Jan 29", "Feb 29", "Mar 29",
]


def month_snake(label: str) -> str:
    """'Feb 24' → 'feb_24'. Lowercase + single-space → underscore."""
    return label.lower().replace(" ", "_")


def month_columns(labels: list[str]) -> list[Column]:
    return [Column(month_snake(l), Float) for l in labels]


def month_column_map(labels: list[str]) -> dict[str, str]:
    return {l: month_snake(l) for l in labels}


def month_type_map(labels: list[str]) -> dict[str, type]:
    return {month_snake(l): float for l in labels}


# Identity columns common to every FTE mart (the first column varies by
# file — Class / Job Type / Department — so it's not included here).
def common_identity_columns(identity_col_name: str) -> list[Column]:
    return [
        Column(identity_col_name, String(120), primary_key=True,
               nullable=False),
        Column("code", String(40)),
        Column("craft_class", String(200)),
        Column("monthly_hours", Float),
        Column("last_month_actuals", Float),
    ]
