"""Productivity service — pure query functions over the productivity marts.

Reads:
  - mart_productivity_labor       (per-phase labor hours)
  - mart_productivity_equipment   (per-phase equipment hours)

Both marts are keyed (tenant_id, job_label, phase_label) and store the
job/phase labels exactly as exported (whitespace-noisy). Every public
function in this module takes a tenant_id and the "external" stripped
form of any job/phase key the API surfaces.

Design notes:

* Labels are normalized by ``_strip_job_key`` / ``_strip_phase_key`` —
  leading whitespace stripped, internal whitespace collapsed. Same
  pattern used by app.modules.jobs.

* Phase status uses earned-value style classification:
    - COMPLETE     pct_complete >= 1.0
    - OVER_BUDGET  pct_used > 1.0 and not complete
    - BEHIND_PACE  pct_used outpaces pct_complete by > pace_band_pct
    - ON_TRACK     pct_used within band, or below pct_complete
    - UNKNOWN      missing inputs (typically est_hours == 0)

* When a phase has both labor and equipment rows, the *worst* status
  drives the phase-level summary count. Priority order:
  OVER_BUDGET > BEHIND_PACE > ON_TRACK > COMPLETE > UNKNOWN.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Engine, text

from app.modules.productivity.schema import (
    AttentionRow,
    JobHoursRollup,
    JobPhaseRow,
    JobProductivityDetail,
    PhasePerf,
    PhaseStatus,
    ProductivityAttention,
    ProductivitySummary,
    ResourceKind,
    ResourceTotals,
)
from app.services.excel_marts.productivity import (
    EQUIPMENT_TABLE_NAME,
    LABOR_TABLE_NAME,
)


# --------------------------------------------------------------------------- #
# Tunables                                                                    #
# --------------------------------------------------------------------------- #

# +/- band around (pct_used == pct_complete) considered on-track.
# 10 pp = burning hours within 10% of where you "should be" given progress.
DEFAULT_PACE_BAND_PCT = 10.0

# Default attention list size.
DEFAULT_TOP_N = 50


# Status priority — higher is worse. Used when comparing labor vs
# equipment for the same phase.
_STATUS_PRIORITY: dict[PhaseStatus, int] = {
    PhaseStatus.OVER_BUDGET: 4,
    PhaseStatus.BEHIND_PACE: 3,
    PhaseStatus.ON_TRACK: 2,
    PhaseStatus.COMPLETE: 1,
    PhaseStatus.UNKNOWN: 0,
}


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _strip_key(s: str | None) -> str:
    """Canonical form: stripped, internal-whitespace collapsed."""
    if s is None:
        return ""
    return " ".join(s.split())


_strip_job_key = _strip_key
_strip_phase_key = _strip_key


def _f(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _normalize_dt(v) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


def _classify(
    actual: float | None,
    est: float | None,
    pct_complete: float | None,
    *,
    pace_band_pct: float,
) -> tuple[PhaseStatus, float | None, float | None]:
    """Return (status, pct_used, SPI).

    SPI = pct_complete / pct_used; >1 ahead, <1 behind.
    """
    if pct_complete is not None and pct_complete >= 1.0:
        # Even if hours blew past estimate, the phase is done — it's
        # historical at this point, not actionable.
        pct_used = (
            actual / est if (actual is not None and est) else None
        )
        spi = (
            pct_complete / pct_used
            if (pct_used and pct_used > 0) else None
        )
        return PhaseStatus.COMPLETE, pct_used, spi

    if est is None or est == 0 or actual is None:
        return PhaseStatus.UNKNOWN, None, None

    pct_used = actual / est
    spi = (
        pct_complete / pct_used
        if (pct_complete is not None and pct_used > 0) else None
    )

    if pct_used > 1.0:
        return PhaseStatus.OVER_BUDGET, pct_used, spi

    if pct_complete is None:
        # Hours are within budget, but no progress data — call it
        # ON_TRACK rather than UNKNOWN so it doesn't stink up the
        # status counts.
        return PhaseStatus.ON_TRACK, pct_used, spi

    band = pace_band_pct / 100.0
    if pct_used > pct_complete + band:
        return PhaseStatus.BEHIND_PACE, pct_used, spi

    return PhaseStatus.ON_TRACK, pct_used, spi


def _severity(
    status: PhaseStatus,
    actual: float | None,
    est: float | None,
    spi: float | None,
) -> float:
    """Severity score for sorting attention rows. Higher = worse.

    OVER_BUDGET    actual - est (raw hours over)
    BEHIND_PACE    actual * (1 - SPI), capped at >= 0
    others         0.0
    """
    if status is PhaseStatus.OVER_BUDGET:
        if actual is None or est is None:
            return 0.0
        return max(0.0, actual - est)
    if status is PhaseStatus.BEHIND_PACE:
        if actual is None or spi is None:
            return 0.0
        return max(0.0, actual * (1.0 - spi))
    return 0.0


def _max_status(a: PhaseStatus, b: PhaseStatus) -> PhaseStatus:
    """Worse of the two statuses, by _STATUS_PRIORITY."""
    return a if _STATUS_PRIORITY[a] >= _STATUS_PRIORITY[b] else b


# --------------------------------------------------------------------------- #
# Data access                                                                 #
# --------------------------------------------------------------------------- #


def _fetch_resource(
    engine: Engine, tenant_id: str, table_name: str,
) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT job_label, phase_label,
                       actual_hours, est_hours, variance_hours,
                       percent_used, percent_complete,
                       units_complete, actual_units,
                       budget_hours, projected_hours_calc,
                       projected_hours_pm, project_end_date
                FROM {table_name}
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
    return [dict(r) for r in rows]


def _make_perf(
    row: dict, kind: ResourceKind, *, pace_band_pct: float,
) -> PhasePerf:
    actual = _f(row.get("actual_hours"))
    est = _f(row.get("est_hours"))
    pct_complete = _f(row.get("percent_complete"))

    status, pct_used, spi = _classify(
        actual, est, pct_complete, pace_band_pct=pace_band_pct,
    )

    # Prefer PM-entered projected_hours; fall back to calculated.
    proj_pm = _f(row.get("projected_hours_pm"))
    proj_calc = _f(row.get("projected_hours_calc"))
    projected = proj_pm if proj_pm is not None else proj_calc

    # variance_hours stored as est - actual; recompute if absent.
    variance = _f(row.get("variance_hours"))
    if variance is None and est is not None and actual is not None:
        variance = est - actual

    # percent_used stored when est != 0; recompute if absent.
    if pct_used is None:
        pct_used = _f(row.get("percent_used"))

    return PhasePerf(
        resource_kind=kind,
        actual_hours=actual,
        est_hours=est,
        variance_hours=variance,
        percent_used=pct_used,
        percent_complete=pct_complete,
        units_complete=_f(row.get("units_complete")),
        actual_units=_f(row.get("actual_units")),
        budget_hours=_f(row.get("budget_hours")),
        projected_hours=projected,
        schedule_performance_index=spi,
        status=status,
    )


# --------------------------------------------------------------------------- #
# Phase universe — labor + equipment combined, indexed by (job, phase) keys  #
# --------------------------------------------------------------------------- #


def _build_phase_universe(
    labor_rows: list[dict],
    equip_rows: list[dict],
    *,
    pace_band_pct: float,
) -> dict[tuple[str, str], dict]:
    """Index every (job_key, phase_key) -> perf info.

    Each value dict carries:
      - labor: PhasePerf | None
      - equipment: PhasePerf | None
      - phase_label: str (raw label, last-write-wins; both marts have it)
      - job_label: str
      - project_end_date: datetime | None
    """
    universe: dict[tuple[str, str], dict] = {}

    def _ingest(rows: list[dict], kind: ResourceKind) -> None:
        for r in rows:
            jkey = _strip_key(r.get("job_label"))
            pkey = _strip_key(r.get("phase_label"))
            if not jkey or not pkey:
                continue
            slot = universe.setdefault(
                (jkey, pkey),
                {
                    "job_label": jkey,
                    "phase_label": pkey,
                    "labor": None,
                    "equipment": None,
                    "project_end_date": None,
                },
            )
            slot[kind.value] = _make_perf(
                r, kind, pace_band_pct=pace_band_pct,
            )
            end = _normalize_dt(r.get("project_end_date"))
            if end is not None and (
                slot["project_end_date"] is None
                or end > slot["project_end_date"]
            ):
                slot["project_end_date"] = end

    _ingest(labor_rows, ResourceKind.LABOR)
    _ingest(equip_rows, ResourceKind.EQUIPMENT)
    return universe


def _phase_worst_status(slot: dict) -> PhaseStatus:
    labor = slot.get("labor")
    equip = slot.get("equipment")
    if labor is None and equip is None:
        return PhaseStatus.UNKNOWN
    if labor is None:
        return equip.status
    if equip is None:
        return labor.status
    return _max_status(labor.status, equip.status)


# --------------------------------------------------------------------------- #
# Public query API                                                            #
# --------------------------------------------------------------------------- #


def get_summary(
    engine: Engine,
    tenant_id: str,
    *,
    pace_band_pct: float = DEFAULT_PACE_BAND_PCT,
) -> ProductivitySummary:
    labor_rows = _fetch_resource(engine, tenant_id, LABOR_TABLE_NAME)
    equip_rows = _fetch_resource(engine, tenant_id, EQUIPMENT_TABLE_NAME)
    universe = _build_phase_universe(
        labor_rows, equip_rows, pace_band_pct=pace_band_pct,
    )

    def _resource_totals(rows: list[dict], kind: ResourceKind) -> ResourceTotals:
        actuals = [_f(r.get("actual_hours")) or 0.0 for r in rows]
        ests = [_f(r.get("est_hours")) or 0.0 for r in rows]
        pcts = [
            _f(r.get("percent_complete")) for r in rows
            if _f(r.get("percent_complete")) is not None
        ]
        sum_a = sum(actuals)
        sum_e = sum(ests)
        return ResourceTotals(
            resource_kind=kind,
            phases=len(rows),
            actual_hours=sum_a,
            est_hours=sum_e,
            percent_used=(sum_a / sum_e) if sum_e else None,
            avg_percent_complete=(sum(pcts) / len(pcts)) if pcts else 0.0,
        )

    labor_totals = _resource_totals(labor_rows, ResourceKind.LABOR)
    equipment_totals = _resource_totals(equip_rows, ResourceKind.EQUIPMENT)

    combined_actual = labor_totals.actual_hours + equipment_totals.actual_hours
    combined_est = labor_totals.est_hours + equipment_totals.est_hours
    combined_used = (
        combined_actual / combined_est if combined_est else None
    )

    # Phase-level status counts (worst across labor/equipment per phase).
    counts = {s: 0 for s in PhaseStatus}
    for slot in universe.values():
        counts[_phase_worst_status(slot)] += 1
    total_phases = len(universe) or 1   # avoid div-by-zero on empty data

    distinct_jobs = {jkey for (jkey, _) in universe.keys()}

    return ProductivitySummary(
        total_jobs=len(distinct_jobs),
        total_phases=len(universe),
        labor_totals=labor_totals,
        equipment_totals=equipment_totals,
        combined_actual_hours=combined_actual,
        combined_est_hours=combined_est,
        combined_percent_used=combined_used,
        phases_complete=counts[PhaseStatus.COMPLETE],
        phases_on_track=counts[PhaseStatus.ON_TRACK],
        phases_behind_pace=counts[PhaseStatus.BEHIND_PACE],
        phases_over_budget=counts[PhaseStatus.OVER_BUDGET],
        phases_unknown=counts[PhaseStatus.UNKNOWN],
        pct_complete=counts[PhaseStatus.COMPLETE] / total_phases,
        pct_on_track=counts[PhaseStatus.ON_TRACK] / total_phases,
        pct_behind_pace=counts[PhaseStatus.BEHIND_PACE] / total_phases,
        pct_over_budget=counts[PhaseStatus.OVER_BUDGET] / total_phases,
        pct_unknown=counts[PhaseStatus.UNKNOWN] / total_phases,
    )


def get_job_detail(
    engine: Engine,
    tenant_id: str,
    job_id: str,
    *,
    pace_band_pct: float = DEFAULT_PACE_BAND_PCT,
) -> JobProductivityDetail | None:
    target = _strip_key(job_id)
    if not target:
        return None

    labor_rows = _fetch_resource(engine, tenant_id, LABOR_TABLE_NAME)
    equip_rows = _fetch_resource(engine, tenant_id, EQUIPMENT_TABLE_NAME)
    universe = _build_phase_universe(
        labor_rows, equip_rows, pace_band_pct=pace_band_pct,
    )

    job_phases = {
        pkey: slot for (jkey, pkey), slot in universe.items()
        if jkey == target
    }
    if not job_phases:
        return None

    rows: list[JobPhaseRow] = []
    counts = {s: 0 for s in PhaseStatus}
    end_dates: list[datetime] = []

    for pkey, slot in job_phases.items():
        worst = _phase_worst_status(slot)
        counts[worst] += 1
        if slot["project_end_date"] is not None:
            end_dates.append(slot["project_end_date"])
        rows.append(
            JobPhaseRow(
                phase_id=pkey,
                phase=slot["phase_label"],
                project_end_date=slot["project_end_date"],
                labor=slot["labor"],
                equipment=slot["equipment"],
                worst_status=worst,
            )
        )

    # Sort phases: worst status first, then phase_id for stability.
    rows.sort(
        key=lambda r: (-_STATUS_PRIORITY[r.worst_status], r.phase_id)
    )

    def _rollup(kind: ResourceKind) -> JobHoursRollup | None:
        slices = [
            (
                p.labor if kind is ResourceKind.LABOR else p.equipment
            )
            for p in rows
        ]
        slices = [s for s in slices if s is not None]
        if not slices:
            return None
        actual = sum(s.actual_hours or 0.0 for s in slices)
        est = sum(s.est_hours or 0.0 for s in slices)
        return JobHoursRollup(
            actual_hours=actual,
            est_hours=est,
            variance_hours=est - actual,
            percent_used=(actual / est) if est else None,
        )

    project_end = max(end_dates) if end_dates else None

    return JobProductivityDetail(
        id=target,
        job=target,
        project_end_date=project_end,
        phases=rows,
        labor_rollup=_rollup(ResourceKind.LABOR),
        equipment_rollup=_rollup(ResourceKind.EQUIPMENT),
        phases_complete=counts[PhaseStatus.COMPLETE],
        phases_on_track=counts[PhaseStatus.ON_TRACK],
        phases_behind_pace=counts[PhaseStatus.BEHIND_PACE],
        phases_over_budget=counts[PhaseStatus.OVER_BUDGET],
        phases_unknown=counts[PhaseStatus.UNKNOWN],
    )


def get_attention(
    engine: Engine,
    tenant_id: str,
    *,
    pace_band_pct: float = DEFAULT_PACE_BAND_PCT,
    resource_kind: ResourceKind | None = None,
    status: PhaseStatus | None = None,
    top_n: int = DEFAULT_TOP_N,
    now: datetime | None = None,
) -> ProductivityAttention:
    """Phases needing attention.

    Returns one row per (job, phase, resource_kind) that is in
    OVER_BUDGET or BEHIND_PACE state. Sorted by severity desc.

    Filters:
      - resource_kind: limit to LABOR or EQUIPMENT (default both)
      - status: limit to OVER_BUDGET or BEHIND_PACE (default both)
      - top_n: cap the number of items returned (1–500)
    """
    now_ = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    labor_rows = _fetch_resource(engine, tenant_id, LABOR_TABLE_NAME)
    equip_rows = _fetch_resource(engine, tenant_id, EQUIPMENT_TABLE_NAME)

    items: list[AttentionRow] = []

    def _emit(rows: list[dict], kind: ResourceKind) -> None:
        if resource_kind is not None and resource_kind is not kind:
            return
        for r in rows:
            jkey = _strip_key(r.get("job_label"))
            pkey = _strip_key(r.get("phase_label"))
            if not jkey or not pkey:
                continue
            perf = _make_perf(r, kind, pace_band_pct=pace_band_pct)
            if perf.status not in (
                PhaseStatus.OVER_BUDGET, PhaseStatus.BEHIND_PACE,
            ):
                continue
            if status is not None and perf.status is not status:
                continue
            sev = _severity(
                perf.status,
                perf.actual_hours, perf.est_hours,
                perf.schedule_performance_index,
            )
            items.append(
                AttentionRow(
                    job_id=jkey,
                    job=jkey,
                    phase_id=pkey,
                    phase=pkey,
                    resource_kind=kind,
                    status=perf.status,
                    actual_hours=perf.actual_hours,
                    est_hours=perf.est_hours,
                    variance_hours=perf.variance_hours,
                    percent_used=perf.percent_used,
                    percent_complete=perf.percent_complete,
                    schedule_performance_index=(
                        perf.schedule_performance_index
                    ),
                    severity=sev,
                )
            )

    _emit(labor_rows, ResourceKind.LABOR)
    _emit(equip_rows, ResourceKind.EQUIPMENT)

    items.sort(key=lambda r: r.severity, reverse=True)
    capped = items[:max(1, min(500, top_n))]

    return ProductivityAttention(
        as_of=now_,
        pace_band_pct=pace_band_pct,
        total=len(items),
        items=capped,
    )
