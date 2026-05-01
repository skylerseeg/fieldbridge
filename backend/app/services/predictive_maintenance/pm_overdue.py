"""Deterministic PM-overdue writer for ``mart_predictive_maintenance``.

Inputs are Vista ``emem`` rows (one per active piece of equipment) that
expose ``HourMeter`` and ``NextPMHours``. For each row we:

  * compute hours-until-PM and bucket into OVERDUE / DUE_SOON / OK,
  * upsert a non-terminal prediction row keyed by
    ``(tenant_id, equipment_id, source='pm_overdue')``,
  * auto-dismiss any previously-open row whose underlying condition has
    cleared (PM recorded → ``NextPMHours`` advanced past ``HourMeter``,
    or equipment retired from ``emem``).

Why ``failure_mode='other'``: the FailureMode enum tags real component
risks (engine / hydraulic / …). Calendar PM is none of those — using
``other`` keeps PM rows from polluting the failure-mode breakdown that
the AI pass owns.

Sync code, single transaction per tenant. Mirrors the SQL conventions
in :mod:`app.modules.predictive_maintenance.service` so reads and
writes go through the same shape of ``text()`` statements.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import Engine, text

from app.services.predictive_maintenance._shared import (
    auto_dismiss,
    ensure_aware,
    insert_prediction,
    now_utc,
    update_prediction,
)


log = logging.getLogger("fieldbridge.predictive_maintenance.pm_overdue")


# --------------------------------------------------------------------------- #
# Tunables                                                                    #
# --------------------------------------------------------------------------- #


# Bucket: hours-until-PM <= 0 → OVERDUE (critical), <= DUE_SOON_HOURS → DUE_SOON
# (medium). Matches the original agent's check_pm_overdue() boundaries.
DUE_SOON_HOURS = 50.0

# Assumed utilization rate for translating hour-meter offsets to a
# calendar pm_due_date. 50 hr/week ≈ 7.14 hr/day (8h × 5 weekdays minus
# weather/idle). Conservative; revisit once mart_equipment_utilization
# is wired in to compute per-equipment rates.
ASSUMED_HOURS_PER_DAY = 7.14

# Cost / downtime defaults by Vista emem.Category. The agent will refine
# these per equipment; this lookup just gives the page a non-NULL number
# so the exposure tile reads sensibly.
_PM_COST_BY_CATEGORY: dict[str, tuple[float, float]] = {
    # category prefix (case-insensitive) → (repair_cost_usd, downtime_hours)
    "EXCAVATOR": (3500.0, 8.0),
    "DOZER": (3500.0, 8.0),
    "LOADER": (3000.0, 6.0),
    "GRADER": (3000.0, 6.0),
    "TRUCK": (1500.0, 4.0),
    "PICKUP": (1200.0, 3.0),
    "TRAILER": (800.0, 2.0),
    "GENERATOR": (1500.0, 3.0),
    "COMPRESSOR": (1500.0, 3.0),
}
_PM_COST_DEFAULT = (2000.0, 6.0)


# --------------------------------------------------------------------------- #
# Result type                                                                 #
# --------------------------------------------------------------------------- #


@dataclass
class PmOverdueResult:
    tenant_id: str
    equipment_seen: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_auto_dismissed: int = 0
    skipped_no_pm_schedule: int = 0
    errors: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Public entrypoint                                                           #
# --------------------------------------------------------------------------- #


def write_pm_overdue(
    engine: Engine,
    tenant_id: str,
    equipment_master: Iterable[dict],
    *,
    now: datetime | None = None,
) -> PmOverdueResult:
    """Run one PM-overdue pass for ``tenant_id``.

    ``equipment_master`` is an iterable of dicts shaped like Vista
    ``emem`` rows. Required keys: ``Equipment``, ``Description``,
    ``HourMeter``, ``NextPMHours``. Optional: ``Category``,
    ``LastPMDate``, ``LastPMHours``.
    """
    result = PmOverdueResult(tenant_id=tenant_id)
    ts = ensure_aware(now or now_utc())

    eq_rows = list(equipment_master)
    result.equipment_seen = len(eq_rows)

    existing = _load_existing(engine, tenant_id)

    with engine.begin() as conn:
        # First pass: upsert rows for OVERDUE / DUE_SOON equipment, track
        # which existing predictions got refreshed.
        refreshed_ids: set[str] = set()

        for eq in eq_rows:
            eq_id = _coalesce_str(eq.get("Equipment"))
            if not eq_id:
                continue

            current_hours = _to_float(eq.get("HourMeter"))
            next_pm = _to_float(eq.get("NextPMHours"))
            if next_pm <= 0:
                result.skipped_no_pm_schedule += 1
                continue

            hours_until_pm = next_pm - current_hours
            if hours_until_pm <= 0:
                bucket, risk_tier = "OVERDUE", "critical"
            elif hours_until_pm <= DUE_SOON_HOURS:
                bucket, risk_tier = "DUE_SOON", "medium"
            else:
                continue  # healthy — handled by auto-dismiss sweep below

            label = _coalesce_str(eq.get("Description"), default=eq_id)
            category = _coalesce_str(eq.get("Category"))
            repair_cost, downtime_hours = _cost_for_category(category)
            pm_due_date = _project_due_date(ts, hours_until_pm)
            evidence = _build_evidence(eq, current_hours, next_pm, hours_until_pm)
            recommended_action = _recommended_action(label, bucket, hours_until_pm)
            description = (
                f"Calendar PM derived from emem: HourMeter={current_hours:.0f}, "
                f"NextPMHours={next_pm:.0f} ({bucket})."
            )

            existing_row = existing.get(eq_id)
            if existing_row is None:
                insert_prediction(
                    conn,
                    tenant_id=tenant_id,
                    equipment_id=eq_id,
                    equipment_label=label,
                    equipment_class=category or None,
                    risk_tier=risk_tier,
                    source="pm_overdue",
                    failure_mode="other",
                    pm_due_date=pm_due_date,
                    estimated_repair_cost=repair_cost,
                    estimated_downtime_hours=downtime_hours,
                    recommended_action=recommended_action,
                    description=description,
                    evidence=evidence,
                    now=ts,
                )
                result.rows_inserted += 1
            else:
                update_prediction(
                    conn,
                    tenant_id=tenant_id,
                    prediction_id=existing_row["id"],
                    equipment_label=label,
                    equipment_class=category or None,
                    risk_tier=risk_tier,
                    pm_due_date=pm_due_date,
                    estimated_repair_cost=repair_cost,
                    estimated_downtime_hours=downtime_hours,
                    recommended_action=recommended_action,
                    description=description,
                    evidence=evidence,
                    now=ts,
                )
                result.rows_updated += 1
                refreshed_ids.add(existing_row["id"])

        # Auto-dismiss sweep: any existing non-terminal pm_overdue row
        # this run did NOT refresh has cleared upstream (PM completed,
        # equipment retired, or was somehow stale).
        for row in existing.values():
            if row["id"] in refreshed_ids:
                continue
            auto_dismiss(
                conn, tenant_id, row["id"], ts,
                note="auto-resolved (PM no longer overdue)",
            )
            result.rows_auto_dismissed += 1

    log.info(
        "pm_overdue tenant=%s seen=%d inserted=%d updated=%d auto_dismissed=%d skipped=%d",
        tenant_id, result.equipment_seen, result.rows_inserted,
        result.rows_updated, result.rows_auto_dismissed,
        result.skipped_no_pm_schedule,
    )
    return result


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _load_existing(engine: Engine, tenant_id: str) -> dict[str, dict]:
    """Map ``equipment_id -> row`` for non-terminal pm_overdue rows."""
    sql = text(
        """
        SELECT id, equipment_id, status
          FROM mart_predictive_maintenance
         WHERE tenant_id = :tenant_id
           AND source = 'pm_overdue'
           AND status NOT IN ('completed', 'dismissed')
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"tenant_id": tenant_id}).mappings().all()
    return {r["equipment_id"]: dict(r) for r in rows}


def _to_float(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _coalesce_str(v, default: str = "") -> str:
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


def _cost_for_category(category: str) -> tuple[float, float]:
    if not category:
        return _PM_COST_DEFAULT
    upper = category.upper()
    for key, value in _PM_COST_BY_CATEGORY.items():
        if upper.startswith(key):
            return value
    return _PM_COST_DEFAULT


def _project_due_date(now: datetime, hours_until_pm: float) -> datetime:
    """Translate an hour-meter offset to a calendar date.

    Uses ``ASSUMED_HOURS_PER_DAY``; negative offsets land in the past
    (which is what the page wants — ``days_until_due < 0`` is the
    overdue signal).
    """
    days = hours_until_pm / ASSUMED_HOURS_PER_DAY
    return now + timedelta(days=days)


def _build_evidence(
    eq: dict, current_hours: float, next_pm: float, hours_until_pm: float,
) -> list[dict]:
    rows = [
        {"label": "Current hour meter", "value": f"{current_hours:,.0f} h"},
        {"label": "Next PM at", "value": f"{next_pm:,.0f} h"},
        {
            "label": "Hours until PM",
            "value": f"{hours_until_pm:,.0f} h"
                     + (" (overdue)" if hours_until_pm <= 0 else ""),
        },
    ]
    last_pm_date = eq.get("LastPMDate")
    if last_pm_date:
        rows.append({"label": "Last PM date", "value": str(last_pm_date)})
    last_pm_hours = eq.get("LastPMHours")
    if last_pm_hours:
        rows.append({"label": "Last PM hours", "value": f"{_to_float(last_pm_hours):,.0f} h"})
    return rows


def _recommended_action(label: str, bucket: str, hours_until_pm: float) -> str:
    if bucket == "OVERDUE":
        return (
            f"Schedule PM for {label} immediately — "
            f"{abs(hours_until_pm):,.0f} h past the next PM threshold."
        )
    return (
        f"Schedule PM for {label} within the next "
        f"{hours_until_pm:,.0f} h of operation."
    )
