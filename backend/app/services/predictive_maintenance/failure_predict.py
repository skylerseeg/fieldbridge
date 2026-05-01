"""AI failure-prediction writer for ``mart_predictive_maintenance``.

For each piece of equipment with sufficient work-order history, calls
:func:`agents.predictive_maintenance.agent.predict_failures` and turns
the agent's output into mart rows. One equipment can produce multiple
open rows (one per distinct ``failure_mode``).

Upsert key:
    ``(tenant_id, equipment_id, source='failure_prediction', failure_mode)``

What this writer does NOT do:
    Auto-dismiss stale rows. Claude's output is non-deterministic —
    if it flags ``engine`` Monday, doesn't flag it Tuesday, and flags
    it again Wednesday, auto-dismissing on Tuesday would create churn
    in the audit log. Resolution of failure-prediction rows is
    user-owned (acknowledge / schedule / complete / dismiss). The
    pm_overdue writer auto-dismisses because that signal IS
    deterministic; this one isn't.

Each Claude call is metered into ``usage_events`` with
``agent='predictive_maintenance'`` for tenant cost attribution.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import Engine, text

from app.models.usage import UsageEvent, calculate_cost
from app.services.predictive_maintenance._shared import (
    ensure_aware,
    insert_prediction,
    now_utc,
    update_prediction,
)


log = logging.getLogger("fieldbridge.predictive_maintenance.failure_predict")


# --------------------------------------------------------------------------- #
# Tunables                                                                    #
# --------------------------------------------------------------------------- #


# Skip equipment with fewer than this many trailing work orders — too
# little signal for the agent to find patterns.
MIN_WO_HISTORY = 2

# Cap per-equipment WO history sent to Claude. Matches the slice the
# agent already takes (`equipment_history[:50]`); explicit here so the
# token budget is visible at the writer.
MAX_WO_PER_CALL = 50

# Default model — kept in sync with the agent module.
DEFAULT_MODEL = "claude-sonnet-4-20250514"


# Component-keyword → FailureMode enum. Order matters (first match
# wins). Keep the right-hand side aligned with the FailureMode enum in
# app/modules/predictive_maintenance/schema.py. Electrical sits above
# engine so "starter motor" / "alternator" don't mis-route through
# bare "motor".
_COMPONENT_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("electrical", "starter", "alternator", "battery", "wiring", "sensor", "ecu"), "electrical"),
    (("hydraulic", "pump", "cylinder", "valve"), "hydraulic"),
    (("transmission", "drivetrain", "final drive", "axle", "differential", "drive shaft"), "drivetrain"),
    (("engine", "fuel", "cooling", "radiator", "head gasket", "turbo"), "engine"),
    (("frame", "undercarriage", "track", "chassis", "boom", "stick"), "structural"),
]


_RISK_LEVEL_MAP = {
    "critical": "critical",
    "high":     "high",
    "medium":   "medium",
    "moderate": "medium",
    "low":      "low",
}


# --------------------------------------------------------------------------- #
# Result type                                                                 #
# --------------------------------------------------------------------------- #


@dataclass
class FailurePredictResult:
    tenant_id: str
    equipment_seen: int = 0
    equipment_analyzed: int = 0
    equipment_skipped_no_history: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    alerts_unmappable: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    errors: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Public entrypoint                                                           #
# --------------------------------------------------------------------------- #


def write_failure_predictions(
    engine: Engine,
    tenant_id: str,
    equipment_master: Iterable[dict],
    work_orders: Iterable[dict],
    *,
    min_wo_history: int = MIN_WO_HISTORY,
    max_equipment: int | None = None,
    model: str = DEFAULT_MODEL,
    now: datetime | None = None,
    agent_call=None,
) -> FailurePredictResult:
    """Run one AI failure-prediction pass for ``tenant_id``.

    ``equipment_master`` is an iterable of Vista ``emem``-shaped dicts
    (Equipment, Description, Category, HourMeter, NextPMHours, …).
    ``work_orders`` is an iterable of Vista ``emwo``-shaped dicts
    (Equipment, Description, OpenDate, ClosedDate, TotalCost, Priority,
    …); the writer groups them by Equipment.

    ``agent_call`` is optional dependency injection for tests — when
    provided it must be ``(equipment_history, pm_schedule) -> (alerts,
    usage)`` matching the upgraded :func:`predict_failures` signature.
    Defaults to the live agent.
    """
    result = FailurePredictResult(tenant_id=tenant_id)
    ts = ensure_aware(now or now_utc())

    eq_rows = list(equipment_master)
    result.equipment_seen = len(eq_rows)

    wo_by_equipment = _group_work_orders(work_orders)
    existing = _load_existing(engine, tenant_id)

    if agent_call is None:
        agent_call = _default_agent_call(model)

    for idx, eq in enumerate(eq_rows):
        if max_equipment is not None and result.equipment_analyzed >= max_equipment:
            break

        eq_id = _coalesce_str(eq.get("Equipment"))
        if not eq_id:
            continue

        history = wo_by_equipment.get(eq_id, [])
        if len(history) < min_wo_history:
            result.equipment_skipped_no_history += 1
            continue

        try:
            alerts, usage = agent_call(history[:MAX_WO_PER_CALL], [eq])
        except Exception as exc:  # noqa: BLE001
            log.exception("agent call failed for tenant=%s eq=%s", tenant_id, eq_id)
            result.errors.append(f"{eq_id}: {type(exc).__name__}: {exc}")
            continue

        result.equipment_analyzed += 1
        if usage:
            result.total_input_tokens += usage.get("input_tokens", 0)
            result.total_output_tokens += usage.get("output_tokens", 0)
            result.total_cost_usd += calculate_cost(
                usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
                usage.get("cache_read_tokens", 0),
                usage.get("cache_write_tokens", 0),
            )
            _record_usage_event(
                engine, tenant_id=tenant_id, equipment_id=eq_id,
                model=model, usage=usage,
            )

        # Map + upsert in a single transaction per equipment.
        with engine.begin() as conn:
            for alert in alerts:
                row = _alert_to_row(eq, alert, ts)
                if row is None:
                    result.alerts_unmappable += 1
                    continue

                key = (eq_id, row["failure_mode"])
                existing_row = existing.get(key)
                if existing_row is None:
                    insert_prediction(
                        conn,
                        tenant_id=tenant_id,
                        source="failure_prediction",
                        **row,
                        now=ts,
                    )
                    result.rows_inserted += 1
                else:
                    # equipment_id + failure_mode form the logical key —
                    # they're set at insert time and never updated here.
                    update_fields = {
                        k: v for k, v in row.items()
                        if k not in {"equipment_id", "failure_mode"}
                    }
                    update_prediction(
                        conn,
                        tenant_id=tenant_id,
                        prediction_id=existing_row["id"],
                        **update_fields,
                        now=ts,
                    )
                    result.rows_updated += 1

    log.info(
        "failure_predict tenant=%s seen=%d analyzed=%d skipped=%d "
        "inserted=%d updated=%d unmappable=%d cost=$%.4f",
        tenant_id, result.equipment_seen, result.equipment_analyzed,
        result.equipment_skipped_no_history, result.rows_inserted,
        result.rows_updated, result.alerts_unmappable,
        result.total_cost_usd,
    )
    return result


# --------------------------------------------------------------------------- #
# Internals                                                                   #
# --------------------------------------------------------------------------- #


def _group_work_orders(work_orders: Iterable[dict]) -> dict[str, list[dict]]:
    """Group emwo rows by Equipment, sorted newest-first by OpenDate."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for wo in work_orders:
        eq = _coalesce_str(wo.get("Equipment"))
        if eq:
            grouped[eq].append(wo)
    for eq, rows in grouped.items():
        rows.sort(key=lambda r: r.get("OpenDate") or "", reverse=True)
    return grouped


def _load_existing(engine: Engine, tenant_id: str) -> dict[tuple[str, str], dict]:
    """Map ``(equipment_id, failure_mode) -> row`` for non-terminal AI rows."""
    sql = text(
        """
        SELECT id, equipment_id, failure_mode
          FROM mart_predictive_maintenance
         WHERE tenant_id = :tenant_id
           AND source = 'failure_prediction'
           AND status NOT IN ('completed', 'dismissed')
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"tenant_id": tenant_id}).mappings().all()
    return {(r["equipment_id"], r["failure_mode"]): dict(r) for r in rows}


def _alert_to_row(eq: dict, alert: dict, now: datetime) -> dict | None:
    """Convert one agent alert into a row payload for insert/update.

    Returns ``None`` if the alert can't be mapped to a FailureMode
    enum value AND lacks any signal we'd surface (e.g. a stub row).
    """
    component = _coalesce_str(alert.get("component_at_risk"))
    failure_mode = _map_failure_mode(component)

    risk_level = str(alert.get("risk_level", "")).lower()
    risk_tier = _RISK_LEVEL_MAP.get(risk_level)
    if risk_tier is None:
        # Fall back to risk_score buckets per the agent's scoring rubric.
        score = _to_float(alert.get("risk_score"))
        if score >= 80:   risk_tier = "critical"
        elif score >= 60: risk_tier = "high"
        elif score >= 40: risk_tier = "medium"
        else:             risk_tier = "low"

    eq_id = _coalesce_str(eq.get("Equipment"))
    label = _coalesce_str(eq.get("Description"), default=eq_id)
    category = _coalesce_str(eq.get("Category")) or None

    urgency_days = _to_float(alert.get("urgency_days"))
    predicted_failure_date = (
        now + timedelta(days=urgency_days) if urgency_days > 0 else None
    )

    description = _coalesce_str(
        alert.get("failure_mode") or alert.get("recommended_action") or component,
        default=f"AI flagged {component or 'unknown component'} on {label}.",
    )
    recommended_action = _coalesce_str(
        alert.get("recommended_action"),
        default=f"Inspect {component or 'flagged component'} on {label}.",
    )

    evidence: list[dict] = []
    raw_evidence = alert.get("evidence") or []
    if isinstance(raw_evidence, list):
        for i, item in enumerate(raw_evidence, start=1):
            evidence.append({"label": f"Signal {i}", "value": str(item)})
    if alert.get("risk_score") is not None:
        evidence.append({"label": "Risk score", "value": f"{alert['risk_score']}/100"})
    parts = alert.get("parts_to_preorder") or []
    if isinstance(parts, list) and parts:
        evidence.append({"label": "Suggested parts", "value": ", ".join(map(str, parts))})

    return {
        "equipment_id": eq_id,
        "equipment_label": label,
        "equipment_class": category,
        "risk_tier": risk_tier,
        "failure_mode": failure_mode,
        "predicted_failure_date": predicted_failure_date,
        "pm_due_date": None,
        "estimated_repair_cost": _to_float_or_none(alert.get("failure_cost_estimate")),
        "estimated_downtime_hours": None,  # agent doesn't return this directly
        "recommended_action": recommended_action,
        "description": description,
        "evidence": evidence,
    }


def _map_failure_mode(component: str) -> str:
    if not component:
        return "other"
    needle = component.lower()
    for keywords, mode in _COMPONENT_KEYWORDS:
        if any(k in needle for k in keywords):
            return mode
    return "other"


def _record_usage_event(
    engine: Engine, *, tenant_id: str, equipment_id: str,
    model: str, usage: dict,
) -> None:
    """Insert a UsageEvent row synchronously (sync mirror of metering.record_usage)."""
    in_tok = usage.get("input_tokens", 0)
    out_tok = usage.get("output_tokens", 0)
    cache_r = usage.get("cache_read_tokens", 0)
    cache_w = usage.get("cache_write_tokens", 0)
    cost = calculate_cost(in_tok, out_tok, cache_r, cache_w)

    event = UsageEvent(
        tenant_id=tenant_id,
        agent="predictive_maintenance",
        model=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cache_read_tokens=cache_r,
        cache_write_tokens=cache_w,
        cost_usd=cost,
        equipment_id=equipment_id[:20],
    )
    try:
        from sqlalchemy.orm import Session
        with Session(engine) as session:
            session.add(event)
            session.commit()
    except Exception as exc:  # noqa: BLE001
        # Metering must never break the writer.
        log.warning("usage_events insert failed for tenant=%s eq=%s: %s",
                    tenant_id, equipment_id, exc)


def _default_agent_call(model: str):
    """Lazy-import the agent so unit tests don't need anthropic installed."""
    def _call(equipment_history: list[dict], pm_schedule: list[dict]):
        from agents.predictive_maintenance import agent as pm_agent
        return pm_agent.predict_failures(
            equipment_history, pm_schedule, return_usage=True,
        )
    _ = model  # reserved — agent module owns its model selection today
    return _call


# --------------------------------------------------------------------------- #
# Tiny coercers (kept local; pm_overdue has its own)                          #
# --------------------------------------------------------------------------- #


def _coalesce_str(v, default: str = "") -> str:
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


def _to_float(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _to_float_or_none(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
