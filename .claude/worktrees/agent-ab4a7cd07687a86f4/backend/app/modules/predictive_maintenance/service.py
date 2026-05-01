"""Predictive Maintenance service — pure query + mutation functions.

Reads two marts:
  * ``mart_predictive_maintenance``         — one row per prediction.
  * ``mart_predictive_maintenance_history`` — append-only audit log.

Plus, on detail reads, joins:
  * ``mart_work_orders`` — last 5 closed WOs for the prediction's
    equipment, surfaced in the detail drawer.

Phase 1 has no writer, so the predictions table is empty in dev. All
endpoints return valid 200s with zeros / empty arrays — that's the
contract; the page must not show error blocks just because no
predictions have been generated yet.

Two key design decisions:

1. **``days_until_due`` is computed in Python at read time**, not in
   SQL. Doing it in SQL would need ``julianday()`` (SQLite-only) or
   ``date_part()`` (Postgres-only); routing through Python keeps the
   marts portable across the dev (Postgres) and CI (SQLite) databases.

2. **List sort + paginate happens in Python after the fetch.** The
   table will always be small (< few thousand rows per tenant) for the
   foreseeable future. If volume grows, swap to dialect-aware ORDER BY
   behind a feature flag.
"""
from __future__ import annotations

import json
import logging
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy import Engine, text

from app.modules.predictive_maintenance.schema import (
    AgingBreakdown,
    CompletedPredictionRow,
    EquipmentExposureRow,
    FailureMode,
    FailureModeBreakdown,
    FailureModeImpactRow,
    MaintSource,
    MaintSourceBreakdown,
    MaintStatus,
    MaintStatusBreakdown,
    PredictionDetail,
    PredictionEvidence,
    PredictionHistoryEntry,
    PredictionListResponse,
    PredictionListRow,
    PredictiveMaintenanceInsights,
    PredictiveMaintenanceSummary,
    RecentWorkOrder,
    RiskTier,
    RiskTierBreakdown,
    TopPredictionRow,
)


log = logging.getLogger("fieldbridge.predictive_maintenance")


# --------------------------------------------------------------------------- #
# Tunables                                                                    #
# --------------------------------------------------------------------------- #


DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 500
DEFAULT_TOP_N = 10
MAX_TOP_N = 100

# Aging buckets used by the insights endpoint.
AGE_FRESH_DAYS = 7      # < 7  -> fresh
AGE_MATURE_DAYS = 30    # 7..30 -> mature; > 30 -> stale

# How many trailing closed work orders to surface on the detail drawer.
RECENT_WORK_ORDERS_LIMIT = 5

# Risk-tier rank for "worst" comparisons (higher = worse).
_RISK_RANK: dict[RiskTier, int] = {
    RiskTier.CRITICAL: 4,
    RiskTier.HIGH: 3,
    RiskTier.MEDIUM: 2,
    RiskTier.LOW: 1,
}

# Status legality: terminal statuses can't transition further.
_TERMINAL_STATUSES: frozenset[MaintStatus] = frozenset(
    {MaintStatus.COMPLETED, MaintStatus.DISMISSED},
)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_dt(v: Any) -> datetime | None:
    """SQLite returns DateTime as ISO strings; coerce back to datetime."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _coalesce_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


def _days_between(later: datetime, earlier: datetime) -> int:
    """Whole-day difference (later - earlier), rounded toward zero."""
    delta = _ensure_aware(later) - _ensure_aware(earlier)
    return int(delta.total_seconds() // 86400)


def _compute_days_until_due(
    *, source: MaintSource,
    pm_due_date: datetime | None,
    predicted_failure_date: datetime | None,
    now: datetime,
) -> int | None:
    """Return ``days_until_due`` (negative if overdue) or None.

    Picks the date column that matches the row's ``source``. Returns
    None when the matching column is NULL — the UI hides the "due in"
    chip in that case rather than showing a misleading value.
    """
    target = pm_due_date if source is MaintSource.PM_OVERDUE else predicted_failure_date
    if target is None:
        return None
    return _days_between(target, now)


def _compute_age_days(created_at: datetime, now: datetime) -> int:
    return max(0, _days_between(now, created_at))


def _safe_enum(cls: type, value: Any, default):
    """Coerce a string to an enum, falling back to ``default`` on miss.

    Defensive — bad data in the table shouldn't 500 the entire page.
    """
    try:
        return cls(value)
    except (ValueError, TypeError):
        return default


def _parse_evidence(blob: str | None) -> list[PredictionEvidence]:
    if not blob:
        return []
    try:
        parsed = json.loads(blob)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    out: list[PredictionEvidence] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        try:
            out.append(
                PredictionEvidence(
                    label=str(item.get("label", "")),
                    value=str(item.get("value", "")),
                    link=item.get("link"),
                )
            )
        except Exception:  # noqa: BLE001 — bad row, skip
            continue
    return out


# --------------------------------------------------------------------------- #
# Row -> ListRow / Detail builders                                            #
# --------------------------------------------------------------------------- #


def _row_to_list_row(r: dict, now: datetime) -> PredictionListRow:
    """Project a raw mart row into the list-shape Pydantic model."""
    source = _safe_enum(MaintSource, r["source"], MaintSource.PM_OVERDUE)
    pm_due = _normalize_dt(r["pm_due_date"])
    predicted = _normalize_dt(r["predicted_failure_date"])
    created = _ensure_aware(_normalize_dt(r["created_at"]) or now)
    updated = _ensure_aware(_normalize_dt(r["updated_at"]) or created)
    scheduled = _normalize_dt(r["scheduled_for"])

    return PredictionListRow(
        id=r["id"],
        equipment_id=_coalesce_str(r["equipment_id"]),
        equipment_label=_coalesce_str(
            r["equipment_label"], _coalesce_str(r["equipment_id"]),
        ),
        risk_tier=_safe_enum(RiskTier, r["risk_tier"], RiskTier.LOW),
        status=_safe_enum(MaintStatus, r["status"], MaintStatus.OPEN),
        source=source,
        failure_mode=_safe_enum(
            FailureMode, r["failure_mode"], FailureMode.OTHER,
        ),
        predicted_failure_date=(
            _ensure_aware(predicted) if predicted else None
        ),
        pm_due_date=_ensure_aware(pm_due) if pm_due else None,
        days_until_due=_compute_days_until_due(
            source=source,
            pm_due_date=pm_due,
            predicted_failure_date=predicted,
            now=now,
        ),
        estimated_downtime_hours=(
            float(r["estimated_downtime_hours"])
            if r["estimated_downtime_hours"] is not None
            else None
        ),
        estimated_repair_cost=(
            float(r["estimated_repair_cost"])
            if r["estimated_repair_cost"] is not None
            else None
        ),
        recommended_action=_coalesce_str(r["recommended_action"]),
        created_at=created,
        updated_at=updated,
        scheduled_for=_ensure_aware(scheduled) if scheduled else None,
        age_days=_compute_age_days(created, now),
    )


# --------------------------------------------------------------------------- #
# Fetch helpers                                                               #
# --------------------------------------------------------------------------- #


_SELECT_ALL = """
    SELECT id, equipment_id, equipment_label, equipment_class,
           risk_tier, status, source, failure_mode,
           predicted_failure_date, pm_due_date,
           estimated_downtime_hours, estimated_repair_cost,
           recommended_action, description,
           created_at, updated_at, scheduled_for,
           evidence_json
      FROM mart_predictive_maintenance
     WHERE tenant_id = :tenant_id
"""


def _fetch_all_rows(engine: Engine, tenant_id: str) -> list[dict]:
    """Pull every prediction row for the tenant.

    Phase 1 datasets are small enough that fetching all rows and
    filtering / sorting in Python is the simpler option. See module
    docstring for the rationale.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(_SELECT_ALL), {"tenant_id": tenant_id},
        ).mappings().all()
    return [dict(r) for r in rows]


def _fetch_one_row(
    engine: Engine, tenant_id: str, prediction_id: str,
) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(
            text(_SELECT_ALL + "       AND id = :id"),
            {"tenant_id": tenant_id, "id": prediction_id},
        ).mappings().first()
    return dict(row) if row else None


def _fetch_history(
    engine: Engine, tenant_id: str, prediction_id: str,
) -> list[PredictionHistoryEntry]:
    sql = text(
        """
        SELECT at, status, note
          FROM mart_predictive_maintenance_history
         WHERE tenant_id = :tenant_id
           AND prediction_id = :prediction_id
         ORDER BY at ASC
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(
            sql, {"tenant_id": tenant_id, "prediction_id": prediction_id},
        ).mappings().all()

    out: list[PredictionHistoryEntry] = []
    for r in rows:
        at = _normalize_dt(r["at"])
        if at is None:
            continue
        out.append(
            PredictionHistoryEntry(
                at=_ensure_aware(at),
                status=_safe_enum(MaintStatus, r["status"], MaintStatus.OPEN),
                note=r["note"],
            )
        )
    return out


def _fetch_recent_work_orders(
    engine: Engine, tenant_id: str, equipment_id: str,
) -> list[RecentWorkOrder]:
    """Last few closed WOs for this equipment.

    Best-effort — wrapped in try/except so a missing/empty mart_work_orders
    table never blocks the detail response.
    """
    sql = text(
        """
        SELECT work_order, description, closed_date, total_cost
          FROM mart_work_orders
         WHERE tenant_id = :tenant_id
           AND equipment = :equipment_id
           AND closed_date IS NOT NULL
         ORDER BY closed_date DESC
         LIMIT :limit
        """
    )
    out: list[RecentWorkOrder] = []
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sql,
                {
                    "tenant_id": tenant_id,
                    "equipment_id": equipment_id,
                    "limit": RECENT_WORK_ORDERS_LIMIT,
                },
            ).mappings().all()
    except Exception as exc:  # noqa: BLE001
        log.warning("recent work orders fetch failed: %s", exc)
        return []

    for r in rows:
        closed = _normalize_dt(r["closed_date"])
        out.append(
            RecentWorkOrder(
                wo_number=_coalesce_str(r["work_order"]),
                description=r["description"],
                closed_at=_ensure_aware(closed) if closed else None,
                cost=(
                    float(r["total_cost"])
                    if r["total_cost"] is not None
                    else None
                ),
            )
        )
    return out


# --------------------------------------------------------------------------- #
# List filter / sort / paginate                                               #
# --------------------------------------------------------------------------- #


_SORT_KEYS: dict[str, Any] = {
    # Risk-tier sort returns the rank directly (CRITICAL=4 > LOW=1) so
    # ``desc`` (reverse=True at the call site) puts CRITICAL first.
    "risk_tier": lambda row: _RISK_RANK.get(row.risk_tier, 0),
    "days_until_due": lambda row: (
        # None days_until_due sort to the back regardless of direction
        row.days_until_due if row.days_until_due is not None else 10**9
    ),
    "estimated_repair_cost": lambda row: (
        row.estimated_repair_cost
        if row.estimated_repair_cost is not None
        else -1.0
    ),
    "estimated_downtime_hours": lambda row: (
        row.estimated_downtime_hours
        if row.estimated_downtime_hours is not None
        else -1.0
    ),
    "equipment_label": lambda row: row.equipment_label.lower(),
    "predicted_failure_date": lambda row: (
        _ensure_aware(row.predicted_failure_date).timestamp()
        if row.predicted_failure_date
        else 10**12
    ),
    "created_at": lambda row: _ensure_aware(row.created_at).timestamp(),
}


def _matches_filters(
    row: PredictionListRow,
    *,
    risk_tier: RiskTier | None,
    status: MaintStatus | None,
    source: MaintSource | None,
    failure_mode: FailureMode | None,
    equipment_id: str | None,
    search: str | None,
    overdue_only: bool,
    min_cost: float | None,
) -> bool:
    if risk_tier is not None and row.risk_tier is not risk_tier:
        return False
    if status is not None and row.status is not status:
        return False
    if source is not None and row.source is not source:
        return False
    if failure_mode is not None and row.failure_mode is not failure_mode:
        return False
    if equipment_id and row.equipment_id != equipment_id:
        return False
    if search:
        needle = search.lower()
        haystack = (
            row.equipment_label.lower()
            + " "
            + row.equipment_id.lower()
            + " "
            + row.recommended_action.lower()
        )
        if needle not in haystack:
            return False
    if overdue_only:
        if row.days_until_due is None or row.days_until_due >= 0:
            return False
    if min_cost is not None:
        if row.estimated_repair_cost is None:
            return False
        if row.estimated_repair_cost < min_cost:
            return False
    return True


# --------------------------------------------------------------------------- #
# Public — list                                                               #
# --------------------------------------------------------------------------- #


def list_predictions(
    engine: Engine,
    tenant_id: str,
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    sort_by: str = "risk_tier",
    sort_dir: str = "desc",
    risk_tier: RiskTier | None = None,
    status: MaintStatus | None = None,
    source: MaintSource | None = None,
    failure_mode: FailureMode | None = None,
    equipment_id: str | None = None,
    search: str | None = None,
    overdue_only: bool = False,
    min_cost: float | None = None,
) -> PredictionListResponse:
    """Paginated, filterable, sortable prediction list."""
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    sort_dir = "asc" if sort_dir.lower() == "asc" else "desc"
    if sort_by not in _SORT_KEYS:
        sort_by = "risk_tier"

    now = _now()
    raw = _fetch_all_rows(engine, tenant_id)
    rows = [_row_to_list_row(r, now) for r in raw]
    rows = [
        r for r in rows
        if _matches_filters(
            r,
            risk_tier=risk_tier,
            status=status,
            source=source,
            failure_mode=failure_mode,
            equipment_id=equipment_id,
            search=search,
            overdue_only=overdue_only,
            min_cost=min_cost,
        )
    ]

    rows.sort(key=_SORT_KEYS[sort_by], reverse=(sort_dir == "desc"))

    total = len(rows)
    start = (page - 1) * page_size
    end = start + page_size
    return PredictionListResponse(
        total=total,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        items=rows[start:end],
    )


# --------------------------------------------------------------------------- #
# Public — summary                                                            #
# --------------------------------------------------------------------------- #


def get_summary(
    engine: Engine, tenant_id: str,
) -> PredictiveMaintenanceSummary:
    """Top-of-page KPI strip."""
    now = _now()
    raw = _fetch_all_rows(engine, tenant_id)
    rows = [_row_to_list_row(r, now) for r in raw]

    status_counts: Counter[MaintStatus] = Counter()
    risk_counts: Counter[RiskTier] = Counter()  # lifetime
    open_risk_counts: Counter[RiskTier] = Counter()
    open_source_counts: Counter[MaintSource] = Counter()
    open_overdue = 0
    open_cost_total = 0.0
    open_downtime_total = 0.0
    open_ages: list[int] = []
    distinct_equipment: set[str] = set()
    distinct_modes: set[FailureMode] = set()

    for r in rows:
        status_counts[r.status] += 1
        risk_counts[r.risk_tier] += 1
        distinct_equipment.add(r.equipment_id)
        distinct_modes.add(r.failure_mode)

        if r.status is MaintStatus.OPEN:
            open_risk_counts[r.risk_tier] += 1
            open_source_counts[r.source] += 1
            if r.days_until_due is not None and r.days_until_due < 0:
                open_overdue += 1
            if r.estimated_repair_cost is not None:
                open_cost_total += r.estimated_repair_cost
            if r.estimated_downtime_hours is not None:
                open_downtime_total += r.estimated_downtime_hours
            open_ages.append(r.age_days)

    avg_age = (
        round(sum(open_ages) / len(open_ages), 2) if open_ages else None
    )
    oldest_age = max(open_ages) if open_ages else None

    return PredictiveMaintenanceSummary(
        total_predictions=len(rows),
        open_count=status_counts[MaintStatus.OPEN],
        acknowledged_count=status_counts[MaintStatus.ACKNOWLEDGED],
        scheduled_count=status_counts[MaintStatus.SCHEDULED],
        completed_count=status_counts[MaintStatus.COMPLETED],
        dismissed_count=status_counts[MaintStatus.DISMISSED],
        critical_count=risk_counts[RiskTier.CRITICAL],
        high_count=risk_counts[RiskTier.HIGH],
        medium_count=risk_counts[RiskTier.MEDIUM],
        low_count=risk_counts[RiskTier.LOW],
        open_critical_count=open_risk_counts[RiskTier.CRITICAL],
        open_overdue_count=open_overdue,
        pm_overdue_count=open_source_counts[MaintSource.PM_OVERDUE],
        failure_prediction_count=open_source_counts[MaintSource.FAILURE_PREDICTION],
        total_estimated_exposure=round(open_cost_total, 2),
        total_estimated_downtime_hours=round(open_downtime_total, 2),
        average_age_days=avg_age,
        oldest_open_age_days=oldest_age,
        distinct_equipment=len(distinct_equipment),
        distinct_failure_modes=len(distinct_modes),
    )


# --------------------------------------------------------------------------- #
# Public — insights                                                           #
# --------------------------------------------------------------------------- #


def _aging_bucket(age_days: int) -> str:
    if age_days < AGE_FRESH_DAYS:
        return "fresh"
    if age_days <= AGE_MATURE_DAYS:
        return "mature"
    return "stale"


def _worst_risk_tier(seen: Iterable[RiskTier]) -> RiskTier:
    return max(seen, key=lambda t: _RISK_RANK.get(t, 0), default=RiskTier.LOW)


def get_insights(
    engine: Engine, tenant_id: str, *, top_n: int = DEFAULT_TOP_N,
) -> PredictiveMaintenanceInsights:
    """Page-body breakdowns + top-N exposure rollups."""
    top_n = max(1, min(top_n, MAX_TOP_N))
    now = _now()
    raw = _fetch_all_rows(engine, tenant_id)
    rows = [_row_to_list_row(r, now) for r in raw]

    # Lifetime breakdowns first (every row).
    risk_counter: Counter[RiskTier] = Counter()
    status_counter: Counter[MaintStatus] = Counter()
    source_counter: Counter[MaintSource] = Counter()
    mode_counter: Counter[FailureMode] = Counter()
    aging_counter: Counter[str] = Counter()

    for r in rows:
        risk_counter[r.risk_tier] += 1
        status_counter[r.status] += 1
        source_counter[r.source] += 1
        mode_counter[r.failure_mode] += 1
        if r.status is MaintStatus.OPEN:
            aging_counter[_aging_bucket(r.age_days)] += 1

    # Per-equipment exposure rollup (open only).
    eq_open_count: Counter[str] = Counter()
    eq_cost_total: dict[str, float] = {}
    eq_downtime_total: dict[str, float] = {}
    eq_label: dict[str, str] = {}
    eq_risks: dict[str, list[RiskTier]] = {}

    # Per-failure-mode exposure rollup (open only).
    mode_open_count: Counter[FailureMode] = Counter()
    mode_cost_total: dict[FailureMode, float] = {}

    # Top-by-exposure pool (open only).
    open_rows: list[PredictionListRow] = []

    # Recent completions — terminal statuses.
    completion_pool: list[PredictionListRow] = []

    for r in rows:
        if r.status is MaintStatus.OPEN:
            eq_open_count[r.equipment_id] += 1
            eq_cost_total[r.equipment_id] = (
                eq_cost_total.get(r.equipment_id, 0.0)
                + (r.estimated_repair_cost or 0.0)
            )
            eq_downtime_total[r.equipment_id] = (
                eq_downtime_total.get(r.equipment_id, 0.0)
                + (r.estimated_downtime_hours or 0.0)
            )
            eq_label[r.equipment_id] = r.equipment_label
            eq_risks.setdefault(r.equipment_id, []).append(r.risk_tier)

            mode_open_count[r.failure_mode] += 1
            mode_cost_total[r.failure_mode] = (
                mode_cost_total.get(r.failure_mode, 0.0)
                + (r.estimated_repair_cost or 0.0)
            )

            open_rows.append(r)

        if r.status in _TERMINAL_STATUSES:
            completion_pool.append(r)

    # Sort + cap for the per-equipment list.
    eq_rollup = [
        EquipmentExposureRow(
            equipment_id=eid,
            equipment_label=eq_label[eid],
            open_count=eq_open_count[eid],
            total_estimated_repair_cost=round(eq_cost_total.get(eid, 0.0), 2),
            total_estimated_downtime_hours=round(
                eq_downtime_total.get(eid, 0.0), 2,
            ),
            worst_risk_tier=_worst_risk_tier(eq_risks.get(eid, [])),
        )
        for eid in eq_open_count
    ]
    eq_rollup.sort(
        key=lambda x: x.total_estimated_repair_cost, reverse=True,
    )
    eq_rollup = eq_rollup[:top_n]

    # Per failure-mode rollup.
    mode_rollup = [
        FailureModeImpactRow(
            failure_mode=mode,
            open_count=mode_open_count[mode],
            total_estimated_repair_cost=round(
                mode_cost_total.get(mode, 0.0), 2,
            ),
        )
        for mode in mode_open_count
    ]
    mode_rollup.sort(
        key=lambda x: x.total_estimated_repair_cost, reverse=True,
    )

    # Top-by-exposure (open rows ranked by cost).
    open_rows.sort(
        key=lambda r: (r.estimated_repair_cost or 0.0), reverse=True,
    )
    top_exposure = [
        TopPredictionRow(
            id=r.id,
            equipment_label=r.equipment_label,
            risk_tier=r.risk_tier,
            failure_mode=r.failure_mode,
            source=r.source,
            estimated_repair_cost=r.estimated_repair_cost,
            days_until_due=r.days_until_due,
            age_days=r.age_days,
        )
        for r in open_rows[:top_n]
    ]

    # Recent completions — sorted by updated_at desc, capped.
    completion_pool.sort(
        key=lambda r: _ensure_aware(r.updated_at).timestamp(), reverse=True,
    )
    recent_completions = [
        CompletedPredictionRow(
            id=r.id,
            equipment_label=r.equipment_label,
            failure_mode=r.failure_mode,
            status=r.status,
            resolved_at=r.updated_at,
        )
        for r in completion_pool[:top_n]
    ]

    return PredictiveMaintenanceInsights(
        risk_tier_breakdown=RiskTierBreakdown(
            critical=risk_counter[RiskTier.CRITICAL],
            high=risk_counter[RiskTier.HIGH],
            medium=risk_counter[RiskTier.MEDIUM],
            low=risk_counter[RiskTier.LOW],
        ),
        status_breakdown=MaintStatusBreakdown(
            open=status_counter[MaintStatus.OPEN],
            acknowledged=status_counter[MaintStatus.ACKNOWLEDGED],
            scheduled=status_counter[MaintStatus.SCHEDULED],
            completed=status_counter[MaintStatus.COMPLETED],
            dismissed=status_counter[MaintStatus.DISMISSED],
        ),
        source_breakdown=MaintSourceBreakdown(
            pm_overdue=source_counter[MaintSource.PM_OVERDUE],
            failure_prediction=source_counter[MaintSource.FAILURE_PREDICTION],
        ),
        failure_mode_breakdown=FailureModeBreakdown(
            engine=mode_counter[FailureMode.ENGINE],
            hydraulic=mode_counter[FailureMode.HYDRAULIC],
            electrical=mode_counter[FailureMode.ELECTRICAL],
            drivetrain=mode_counter[FailureMode.DRIVETRAIN],
            structural=mode_counter[FailureMode.STRUCTURAL],
            other=mode_counter[FailureMode.OTHER],
        ),
        aging_breakdown=AgingBreakdown(
            fresh=aging_counter["fresh"],
            mature=aging_counter["mature"],
            stale=aging_counter["stale"],
        ),
        top_equipment_exposure=eq_rollup,
        failure_mode_impact=mode_rollup,
        top_by_exposure=top_exposure,
        recent_completions=recent_completions,
    )


# --------------------------------------------------------------------------- #
# Public — detail                                                             #
# --------------------------------------------------------------------------- #


def get_detail(
    engine: Engine, tenant_id: str, prediction_id: str,
) -> PredictionDetail:
    """Full payload for the detail drawer."""
    raw = _fetch_one_row(engine, tenant_id, prediction_id)
    if raw is None:
        raise HTTPException(status_code=404, detail="Prediction not found.")

    now = _now()
    list_row = _row_to_list_row(raw, now)
    history = _fetch_history(engine, tenant_id, prediction_id)
    work_orders = _fetch_recent_work_orders(
        engine, tenant_id, list_row.equipment_id,
    )
    evidence = _parse_evidence(raw.get("evidence_json"))

    return PredictionDetail(
        id=list_row.id,
        equipment_id=list_row.equipment_id,
        equipment_label=list_row.equipment_label,
        equipment_class=raw.get("equipment_class"),
        risk_tier=list_row.risk_tier,
        status=list_row.status,
        source=list_row.source,
        failure_mode=list_row.failure_mode,
        predicted_failure_date=list_row.predicted_failure_date,
        pm_due_date=list_row.pm_due_date,
        days_until_due=list_row.days_until_due,
        estimated_downtime_hours=list_row.estimated_downtime_hours,
        estimated_repair_cost=list_row.estimated_repair_cost,
        recommended_action=list_row.recommended_action,
        description=_coalesce_str(raw.get("description")),
        created_at=list_row.created_at,
        updated_at=list_row.updated_at,
        scheduled_for=list_row.scheduled_for,
        age_days=list_row.age_days,
        evidence=evidence,
        recent_work_orders=work_orders,
        history=history,
    )


# --------------------------------------------------------------------------- #
# Mutations                                                                   #
# --------------------------------------------------------------------------- #


def _ensure_not_terminal(prediction_id: str, current: MaintStatus) -> None:
    """Block transitions out of completed/dismissed."""
    if current in _TERMINAL_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Prediction {prediction_id} is in terminal status "
                f"'{current.value}' and cannot be modified."
            ),
        )


def _apply_transition(
    engine: Engine,
    tenant_id: str,
    prediction_id: str,
    *,
    new_status: MaintStatus,
    note: str | None,
    scheduled_for: datetime | None = None,
    set_scheduled_to_null: bool = False,
) -> PredictionDetail:
    """Update the row + append a history entry in one transaction.

    Returns the freshly-fetched detail payload so the frontend can apply
    optimistic updates and reconcile with the server response.
    """
    now = _now()

    update_sql_parts = ["status = :status", "updated_at = :updated_at"]
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "id": prediction_id,
        "status": new_status.value,
        "updated_at": now,
    }
    if scheduled_for is not None:
        update_sql_parts.append("scheduled_for = :scheduled_for")
        params["scheduled_for"] = _ensure_aware(scheduled_for)
    elif set_scheduled_to_null:
        update_sql_parts.append("scheduled_for = NULL")

    update_sql = text(
        f"""
        UPDATE mart_predictive_maintenance
           SET {", ".join(update_sql_parts)}
         WHERE tenant_id = :tenant_id
           AND id = :id
        """
    )

    history_sql = text(
        """
        INSERT INTO mart_predictive_maintenance_history
            (tenant_id, prediction_id, at, status, note)
        VALUES (:tenant_id, :prediction_id, :at, :status, :note)
        """
    )

    with engine.begin() as conn:
        # Verify row exists + read current status for legality check.
        current = conn.execute(
            text(
                """
                SELECT status
                  FROM mart_predictive_maintenance
                 WHERE tenant_id = :tenant_id
                   AND id = :id
                """
            ),
            {"tenant_id": tenant_id, "id": prediction_id},
        ).scalar_one_or_none()
        if current is None:
            raise HTTPException(
                status_code=404, detail="Prediction not found.",
            )

        current_enum = _safe_enum(MaintStatus, current, MaintStatus.OPEN)
        _ensure_not_terminal(prediction_id, current_enum)

        conn.execute(update_sql, params)
        conn.execute(
            history_sql,
            {
                "tenant_id": tenant_id,
                "prediction_id": prediction_id,
                "at": now,
                "status": new_status.value,
                "note": note,
            },
        )

    return get_detail(engine, tenant_id, prediction_id)


def acknowledge(
    engine: Engine, tenant_id: str, prediction_id: str, *, note: str | None,
) -> PredictionDetail:
    return _apply_transition(
        engine, tenant_id, prediction_id,
        new_status=MaintStatus.ACKNOWLEDGED, note=note,
    )


def schedule(
    engine: Engine,
    tenant_id: str,
    prediction_id: str,
    *,
    scheduled_for: datetime,
    note: str | None,
) -> PredictionDetail:
    return _apply_transition(
        engine, tenant_id, prediction_id,
        new_status=MaintStatus.SCHEDULED,
        note=note,
        scheduled_for=scheduled_for,
    )


def complete(
    engine: Engine,
    tenant_id: str,
    prediction_id: str,
    *,
    completed_at: datetime | None,
    note: str | None,
) -> PredictionDetail:
    # ``completed_at`` is recorded in the history note if provided —
    # the row's own ``updated_at`` becomes the authoritative resolution
    # timestamp surfaced by ``recent_completions``.
    audit_note = note
    if completed_at is not None:
        marker = f"completed_at={_ensure_aware(completed_at).isoformat()}"
        audit_note = f"{marker}; {note}" if note else marker
    return _apply_transition(
        engine, tenant_id, prediction_id,
        new_status=MaintStatus.COMPLETED,
        note=audit_note,
    )


def dismiss(
    engine: Engine,
    tenant_id: str,
    prediction_id: str,
    *,
    reason: str | None,
) -> PredictionDetail:
    return _apply_transition(
        engine, tenant_id, prediction_id,
        new_status=MaintStatus.DISMISSED,
        note=reason,
    )


# --------------------------------------------------------------------------- #
# Test/dev helper — seed a row                                                #
# --------------------------------------------------------------------------- #


def insert_prediction(
    engine: Engine,
    tenant_id: str,
    *,
    equipment_id: str,
    equipment_label: str,
    risk_tier: RiskTier,
    source: MaintSource,
    failure_mode: FailureMode,
    recommended_action: str,
    description: str = "",
    equipment_class: str | None = None,
    status: MaintStatus = MaintStatus.OPEN,
    predicted_failure_date: datetime | None = None,
    pm_due_date: datetime | None = None,
    estimated_downtime_hours: float | None = None,
    estimated_repair_cost: float | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    scheduled_for: datetime | None = None,
    evidence: list[dict] | None = None,
    prediction_id: str | None = None,
) -> str:
    """Insert one prediction row and return its id.

    Convenience for tests and ad-hoc dev seeding. Real ingest will live
    in a separate writer module (Phase 2 — agent-driven, not built yet).
    """
    pid = prediction_id or str(uuid.uuid4())
    now = _now()
    created = _ensure_aware(created_at or now)
    updated = _ensure_aware(updated_at or created)
    scheduled = _ensure_aware(scheduled_for) if scheduled_for else None

    sql = text(
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
            :risk_tier, :status, :source, :failure_mode,
            :predicted_failure_date, :pm_due_date,
            :estimated_downtime_hours, :estimated_repair_cost,
            :recommended_action, :description,
            :created_at, :updated_at, :scheduled_for,
            :evidence_json
        )
        """
    )
    with engine.begin() as conn:
        conn.execute(
            sql,
            {
                "tenant_id": tenant_id,
                "id": pid,
                "equipment_id": equipment_id,
                "equipment_label": equipment_label,
                "equipment_class": equipment_class,
                "risk_tier": risk_tier.value,
                "status": status.value,
                "source": source.value,
                "failure_mode": failure_mode.value,
                "predicted_failure_date": (
                    _ensure_aware(predicted_failure_date)
                    if predicted_failure_date
                    else None
                ),
                "pm_due_date": (
                    _ensure_aware(pm_due_date) if pm_due_date else None
                ),
                "estimated_downtime_hours": estimated_downtime_hours,
                "estimated_repair_cost": estimated_repair_cost,
                "recommended_action": recommended_action,
                "description": description,
                "created_at": created,
                "updated_at": updated,
                "scheduled_for": scheduled,
                "evidence_json": (
                    json.dumps(evidence) if evidence is not None else None
                ),
            },
        )
    return pid
