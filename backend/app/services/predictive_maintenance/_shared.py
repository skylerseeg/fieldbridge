"""Row-level helpers shared by every ``mart_predictive_maintenance`` writer.

INSERT / UPDATE / AUTO-DISMISS primitives that take a SQLAlchemy
``Connection`` (so callers control the surrounding transaction). Both
the deterministic ``pm_overdue`` writer and the AI ``failure_predict``
writer share these — they differ in *upsert key* logic, not in the
shape of a single row write.

History rows are written only on status transitions (auto-dismiss).
Refreshing derived fields (risk_tier, evidence, …) without changing
status is intentional — the user-owned lifecycle (acknowledge,
schedule, complete, dismiss) lives in the read service.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import text


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def insert_prediction(
    conn,
    *,
    tenant_id: str,
    equipment_id: str,
    equipment_label: str,
    equipment_class: str | None,
    risk_tier: str,
    source: str,
    failure_mode: str,
    recommended_action: str,
    description: str,
    evidence: list[dict],
    now: datetime,
    predicted_failure_date: datetime | None = None,
    pm_due_date: datetime | None = None,
    estimated_repair_cost: float | None = None,
    estimated_downtime_hours: float | None = None,
) -> str:
    """Insert one open prediction row. Returns the new UUID."""
    pid = str(uuid.uuid4())
    conn.execute(
        text(
            """
            INSERT INTO mart_predictive_maintenance (
                tenant_id, id,
                equipment_id, equipment_label, equipment_class,
                risk_tier, status, source, failure_mode,
                predicted_failure_date, pm_due_date,
                estimated_downtime_hours, estimated_repair_cost,
                recommended_action, description,
                created_at, updated_at, scheduled_for,
                evidence_json
            ) VALUES (
                :tenant_id, :id,
                :equipment_id, :equipment_label, :equipment_class,
                :risk_tier, 'open', :source, :failure_mode,
                :predicted_failure_date, :pm_due_date,
                :downtime_hours, :repair_cost,
                :recommended_action, :description,
                :now, :now, NULL,
                :evidence_json
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "id": pid,
            "equipment_id": equipment_id,
            "equipment_label": equipment_label,
            "equipment_class": equipment_class,
            "risk_tier": risk_tier,
            "source": source,
            "failure_mode": failure_mode,
            "predicted_failure_date": (
                ensure_aware(predicted_failure_date)
                if predicted_failure_date else None
            ),
            "pm_due_date": ensure_aware(pm_due_date) if pm_due_date else None,
            "downtime_hours": estimated_downtime_hours,
            "repair_cost": estimated_repair_cost,
            "recommended_action": recommended_action,
            "description": description,
            "now": now,
            "evidence_json": json.dumps(evidence),
        },
    )
    return pid


def update_prediction(
    conn,
    *,
    tenant_id: str,
    prediction_id: str,
    equipment_label: str,
    equipment_class: str | None,
    risk_tier: str,
    recommended_action: str,
    description: str,
    evidence: list[dict],
    now: datetime,
    predicted_failure_date: datetime | None = None,
    pm_due_date: datetime | None = None,
    estimated_repair_cost: float | None = None,
    estimated_downtime_hours: float | None = None,
) -> None:
    """Refresh derived fields without changing status (user-owned)."""
    conn.execute(
        text(
            """
            UPDATE mart_predictive_maintenance
               SET equipment_label = :equipment_label,
                   equipment_class = :equipment_class,
                   risk_tier = :risk_tier,
                   predicted_failure_date = :predicted_failure_date,
                   pm_due_date = :pm_due_date,
                   estimated_repair_cost = :repair_cost,
                   estimated_downtime_hours = :downtime_hours,
                   recommended_action = :recommended_action,
                   description = :description,
                   evidence_json = :evidence_json,
                   updated_at = :now
             WHERE tenant_id = :tenant_id
               AND id = :id
            """
        ),
        {
            "tenant_id": tenant_id,
            "id": prediction_id,
            "equipment_label": equipment_label,
            "equipment_class": equipment_class,
            "risk_tier": risk_tier,
            "predicted_failure_date": (
                ensure_aware(predicted_failure_date)
                if predicted_failure_date else None
            ),
            "pm_due_date": ensure_aware(pm_due_date) if pm_due_date else None,
            "repair_cost": estimated_repair_cost,
            "downtime_hours": estimated_downtime_hours,
            "recommended_action": recommended_action,
            "description": description,
            "evidence_json": json.dumps(evidence),
            "now": now,
        },
    )


def auto_dismiss(
    conn, tenant_id: str, prediction_id: str, now: datetime, note: str,
) -> None:
    """Move a stale open row to dismissed + write a history entry."""
    conn.execute(
        text(
            """
            UPDATE mart_predictive_maintenance
               SET status = 'dismissed', updated_at = :now
             WHERE tenant_id = :tenant_id
               AND id = :id
            """
        ),
        {"tenant_id": tenant_id, "id": prediction_id, "now": now},
    )
    conn.execute(
        text(
            """
            INSERT INTO mart_predictive_maintenance_history
                (tenant_id, prediction_id, at, status, note)
            VALUES (:tenant_id, :prediction_id, :at, 'dismissed', :note)
            """
        ),
        {
            "tenant_id": tenant_id,
            "prediction_id": prediction_id,
            "at": now,
            "note": note,
        },
    )
