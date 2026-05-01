"""predictive_maintenance — equipment failure prediction + PM queue.

Source: none (no Excel sheet). Rows are produced by future writers —
either ``agents.predictive_maintenance.agent.predict_failures`` calling
the Anthropic API, or a calendar-rule job that walks
``mart_equipment_utilization`` looking for overdue PMs. Neither writer
exists yet; the tables below are registered on ``Base.metadata`` so
``create_mart_tables.py`` builds them and the
:mod:`app.modules.predictive_maintenance` service can read from an empty
table without 500ing.

Two tables:

  * ``mart_predictive_maintenance``         — one row per prediction.
  * ``mart_predictive_maintenance_history`` — append-only audit log of
    status transitions (acknowledge / schedule / complete / dismiss).

Dedupe:
  * predictions: (tenant_id, id) — ``id`` is a UUID4 produced server-side
    at insert time. There is no obvious natural key — one piece of
    equipment can have multiple open predictions at once (e.g. a
    pm_overdue row + a failure_prediction row in different failure
    modes).
  * history: (tenant_id, prediction_id, at) — at-microsecond resolution
    a single prediction can't have two transitions in the same instant.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.services.excel_marts._base import (
    Column, DateTime, Float, String, Text, mart,
)

TABLE_NAME = "mart_predictive_maintenance"
HISTORY_TABLE_NAME = "mart_predictive_maintenance_history"


# Primary prediction row. Mirrors PredictionDetail in
# app/modules/predictive_maintenance/schema.py — keep them in lockstep.
table = mart(
    TABLE_NAME,
    Column("id", String(36), primary_key=True, nullable=False),

    # Equipment linkage. ``equipment_id`` matches
    # mart_equipment_utilization.truck (String(80)). ``equipment_label``
    # is denormalized onto the row at insert time so reads are flat —
    # mart_asset_barcodes has no canonical "label" column.
    Column("equipment_id", String(80), nullable=False),
    Column("equipment_label", String(255), nullable=False),
    Column("equipment_class", String(80)),

    # Classification (all four are short enums; see
    # app/modules/predictive_maintenance/schema.py for valid values).
    Column("risk_tier", String(16), nullable=False),
    Column("status", String(16), nullable=False),
    Column("source", String(20), nullable=False),
    Column("failure_mode", String(20), nullable=False),

    # Date axes. Exactly one of pm_due_date / predicted_failure_date
    # is set per row (driven by ``source``); the other is NULL.
    Column("predicted_failure_date", DateTime),
    Column("pm_due_date", DateTime),

    Column("estimated_downtime_hours", Float),
    Column("estimated_repair_cost", Float),

    Column("recommended_action", Text, nullable=False),
    Column("description", Text, nullable=False),

    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
    Column("scheduled_for", DateTime),

    # JSON-encoded list[{label, value, link}] surfaced in the detail
    # drawer. Stored as Text for SQLite portability.
    Column("evidence_json", Text),
)


# Append-only status-transition log. One row per acknowledge / schedule /
# complete / dismiss event. Used to render PredictionDetail.history.
history_table = mart(
    HISTORY_TABLE_NAME,
    Column("prediction_id", String(36), primary_key=True, nullable=False),
    Column("at", DateTime, primary_key=True, nullable=False),
    Column("status", String(16), nullable=False),
    Column("note", Text),
)


class PredictionRow(BaseModel):
    """ORM-shape mirror of ``mart_predictive_maintenance``.

    Used by tests and any future writer; not consumed by the read path
    (which goes through raw SQL + the response Pydantic models).
    """

    tenant_id: str
    id: str
    equipment_id: str
    equipment_label: str
    equipment_class: str | None = None
    risk_tier: str
    status: str
    source: str
    failure_mode: str
    predicted_failure_date: datetime | None = None
    pm_due_date: datetime | None = None
    estimated_downtime_hours: float | None = None
    estimated_repair_cost: float | None = None
    recommended_action: str
    description: str
    created_at: datetime
    updated_at: datetime
    scheduled_for: datetime | None = None
    evidence_json: str | None = None


class PredictionHistoryRow(BaseModel):
    """ORM-shape mirror of ``mart_predictive_maintenance_history``."""

    tenant_id: str
    prediction_id: str
    at: datetime
    status: str
    note: str | None = None
