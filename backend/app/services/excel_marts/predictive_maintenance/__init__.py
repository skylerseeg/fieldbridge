"""predictive_maintenance mart — equipment failure predictions + PM queue.

No Excel ingest job: rows are produced by future writers (agent or
calendar-rule scheduler), not by an .xlsx import. The Tables are
registered on ``Base.metadata`` so ``scripts/create_mart_tables.py``
builds them; the :mod:`app.modules.predictive_maintenance` service
reads from them directly.

Excluded from ``MART_MODULES`` for the same reason ``work_orders`` is —
``list_marts()`` describes ingest jobs, and these tables don't have
one yet.
"""
from app.services.excel_marts.predictive_maintenance.schema import (
    HISTORY_TABLE_NAME,
    TABLE_NAME,
    PredictionHistoryRow,
    PredictionRow,
    history_table,
    table,
)

__all__ = [
    "HISTORY_TABLE_NAME",
    "TABLE_NAME",
    "PredictionHistoryRow",
    "PredictionRow",
    "history_table",
    "table",
]
