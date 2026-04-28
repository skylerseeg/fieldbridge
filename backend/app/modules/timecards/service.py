"""Timecards service — pure query functions against the SQLite marts.

Reads from four marts:
  - mart_fte_class_actual       (Feb 24 – Jan 25, 12 months)
  - mart_fte_class_projected    (Apr 26 – Mar 29, 36 months)
  - mart_fte_overhead_actual    (12 months, keyed by department)
  - mart_fte_type_actual        (12 months, keyed by job_type)

Actuals and projections do NOT share months today, so variance is
computed against the rolling ``avg_12mo_a`` that both files carry.
When Vista v2 lands, actuals and projections will share a month index
and we'll add month-by-month variance — the response shape already
supports that via ``MonthlyPoint``.

Overtime proxy: each FTE row carries ``monthly_hours`` (budget) and
``last_month_actuals`` (actual hours/FTE last month). Overtime =
``max(0, actual - budget)``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import Engine, text

from app.modules.timecards.schema import (
    MonthlyPoint,
    OverheadRatio,
    OvertimeByClass,
    TimecardDetail,
    TimecardInsights,
    TimecardListResponse,
    TimecardListRow,
    TimecardSummary,
    VarianceByClass,
    VarianceStatus,
)
from app.services.excel_marts._fte_shared import (
    MONTHS_24_25, MONTHS_26_29, month_snake,
)


# --------------------------------------------------------------------------- #
# Tunables                                                                    #
# --------------------------------------------------------------------------- #

# ± band (percentage points) around projected where we call the class
# "on track". Wider than typical financial variance because FTE churns
# month-to-month and anything tighter would fire constantly.
DEFAULT_VARIANCE_BAND_PCT = 10.0

# Top-N cap for the insights lists. The screen shows ~10 rows per panel.
DEFAULT_TOP_N = 10


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


SortField = Literal[
    "class_name", "actual_avg_fte", "projected_avg_fte",
    "variance", "variance_pct", "overtime_pct",
    "monthly_hours", "last_month_actuals",
]
SortDir = Literal["asc", "desc"]


def _variance_status(
    actual: float | None,
    projected: float | None,
    band_pct: float,
) -> tuple[float | None, float | None, VarianceStatus]:
    """Return ``(variance, variance_pct, status)``.

    ``variance = actual - projected``. Status is ``unknown`` whenever
    projected is zero or missing — we can't compute a percentage.
    """
    if actual is None or projected is None:
        return None, None, VarianceStatus.UNKNOWN
    variance = actual - projected
    if projected == 0:
        return variance, None, VarianceStatus.UNKNOWN
    pct = variance / projected * 100.0
    if pct > band_pct:
        return variance, pct, VarianceStatus.OVER
    if pct < -band_pct:
        return variance, pct, VarianceStatus.UNDER
    return variance, pct, VarianceStatus.ON_TRACK


def _overtime(
    monthly_hours: float | None,
    last_month_actuals: float | None,
) -> tuple[float | None, float | None]:
    """Return ``(overtime_hours, overtime_pct)``.

    Definitions:
      overtime_hours = max(0, last_month_actuals - monthly_hours)
      overtime_pct   = overtime_hours / monthly_hours * 100.0

    Both None when either input is missing or monthly_hours is 0.
    """
    if monthly_hours is None or last_month_actuals is None:
        return None, None
    if monthly_hours == 0:
        return None, None
    ot_hours = max(0.0, last_month_actuals - monthly_hours)
    return ot_hours, ot_hours / monthly_hours * 100.0


def _f(v) -> float | None:
    """Coerce a DB value to float, preserving None."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fetch_class_actual(engine: Engine, tenant_id: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT * FROM mart_fte_class_actual
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
    return [dict(r) for r in rows]


def _fetch_class_projected(engine: Engine, tenant_id: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT * FROM mart_fte_class_projected
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
    return [dict(r) for r in rows]


def _fetch_overhead_actual_total(engine: Engine, tenant_id: str) -> float:
    """Sum of overhead avg_12mo_a across all departments."""
    with engine.connect() as conn:
        total = conn.execute(
            text(
                """
                SELECT COALESCE(SUM(avg_12mo_a), 0.0)
                FROM mart_fte_overhead_actual
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).scalar()
    return float(total or 0.0)


def _count(engine: Engine, tenant_id: str, table: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            ).scalar()
            or 0
        )


def _combine(
    actual_rows: list[dict],
    projected_rows: list[dict],
    band_pct: float,
) -> list[TimecardListRow]:
    """Full-outer-join actual + projected on class_name and build rows."""
    proj_by_name = {r["class_name"]: r for r in projected_rows}
    seen: set[str] = set()
    out: list[TimecardListRow] = []

    for a in actual_rows:
        name = a["class_name"]
        seen.add(name)
        p = proj_by_name.get(name)
        out.append(_build_row(a, p, band_pct))

    # Classes that appear only in the projected mart — rare but possible.
    for name, p in proj_by_name.items():
        if name in seen:
            continue
        out.append(_build_row(None, p, band_pct))

    return out


def _build_row(
    a: dict | None,
    p: dict | None,
    band_pct: float,
) -> TimecardListRow:
    # Identity columns prefer the actuals row (it's the authoritative
    # "what happened" source); fall back to projected for class-only rows.
    src = a or p or {}
    name = src["class_name"]
    code = src.get("code")
    craft_class = src.get("craft_class")

    monthly_hours = _f(src.get("monthly_hours"))
    last_month_actuals = _f(src.get("last_month_actuals")) if a else None

    actual_avg = _f(a.get("avg_12mo_a")) if a else None
    projected_avg = _f(p.get("avg_12mo_a")) if p else None

    variance, variance_pct, status = _variance_status(
        actual_avg, projected_avg, band_pct,
    )
    overtime_hours, overtime_pct = _overtime(monthly_hours, last_month_actuals)

    return TimecardListRow(
        id=name,
        class_name=name,
        code=code,
        craft_class=craft_class,
        monthly_hours=monthly_hours,
        last_month_actuals=last_month_actuals,
        actual_avg_fte=actual_avg,
        projected_avg_fte=projected_avg,
        variance=variance,
        variance_pct=variance_pct,
        variance_status=status,
        overtime_hours=overtime_hours,
        overtime_pct=overtime_pct,
    )


def _monthly_breakdown(
    a: dict | None,
    p: dict | None,
) -> list[MonthlyPoint]:
    """Interleave actual (Feb 24–Jan 25) and projected (Apr 26–Mar 29)
    months into one chronologically-ordered list.

    Since the two windows don't overlap today, each MonthlyPoint has
    only one side populated. When Vista v2 collapses them into a single
    window this still works — same row gets both fields.
    """
    # Build (label, actual, projected) rows keyed by label order across
    # the union of both windows.
    labels: list[str] = []
    seen: set[str] = set()
    for lbl in MONTHS_24_25 + MONTHS_26_29:
        if lbl in seen:
            continue
        seen.add(lbl)
        labels.append(lbl)

    out: list[MonthlyPoint] = []
    for lbl in labels:
        col = month_snake(lbl)
        actual = _f(a.get(col)) if (a and col in a) else None
        projected = _f(p.get(col)) if (p and col in p) else None
        if actual is None and projected is None:
            continue
        out.append(MonthlyPoint(month=lbl, actual=actual, projected=projected))
    return out


# --------------------------------------------------------------------------- #
# Public query API                                                            #
# --------------------------------------------------------------------------- #


def get_summary(
    engine: Engine,
    tenant_id: str,
    *,
    band_pct: float = DEFAULT_VARIANCE_BAND_PCT,
) -> TimecardSummary:
    actual = _fetch_class_actual(engine, tenant_id)
    projected = _fetch_class_projected(engine, tenant_id)
    rows = _combine(actual, projected, band_pct)

    total_actual = sum(r.actual_avg_fte or 0.0 for r in rows)
    total_projected = sum(r.projected_avg_fte or 0.0 for r in rows)

    total_variance_pct: float | None
    if total_projected:
        total_variance_pct = (
            (total_actual - total_projected) / total_projected * 100.0
        )
    else:
        total_variance_pct = None

    overtime_rows = [r for r in rows if r.overtime_pct is not None]
    if overtime_rows:
        avg_overtime_pct = sum(r.overtime_pct for r in overtime_rows) / len(
            overtime_rows
        )
    else:
        avg_overtime_pct = 0.0
    classes_with_overtime = sum(
        1 for r in rows if (r.overtime_hours or 0.0) > 0.0
    )

    direct_fte = total_actual
    overhead_fte = _fetch_overhead_actual_total(engine, tenant_id)
    denom = direct_fte + overhead_fte
    overhead_ratio_pct = (overhead_fte / denom * 100.0) if denom else None

    return TimecardSummary(
        total_classes=_count(engine, tenant_id, "mart_fte_class_actual"),
        total_overhead_departments=_count(
            engine, tenant_id, "mart_fte_overhead_actual",
        ),
        total_job_types=_count(engine, tenant_id, "mart_fte_type_actual"),
        total_actual_fte=total_actual,
        total_projected_fte=total_projected,
        total_variance_pct=total_variance_pct,
        avg_overtime_pct=avg_overtime_pct,
        classes_with_overtime=classes_with_overtime,
        overhead_ratio_pct=overhead_ratio_pct,
    )


def list_timecards(
    engine: Engine,
    tenant_id: str,
    *,
    page: int = 1,
    page_size: int = 25,
    sort_by: SortField = "variance_pct",
    sort_dir: SortDir = "desc",
    status: VarianceStatus | None = None,
    search: str | None = None,
    overtime_only: bool | None = None,
    band_pct: float = DEFAULT_VARIANCE_BAND_PCT,
) -> TimecardListResponse:
    """Paginated, filtered, sorted list.

    Filtering + sorting happens in Python after the two mart reads so
    the derived columns (variance, overtime_pct, variance_status) can
    participate. Row volumes are ≈30 classes per tenant — fine in-memory.
    """
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 500:
        page_size = 25
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"

    actual = _fetch_class_actual(engine, tenant_id)
    projected = _fetch_class_projected(engine, tenant_id)
    rows = _combine(actual, projected, band_pct)

    # --- filters
    if status is not None:
        rows = [r for r in rows if r.variance_status is status]
    if overtime_only is True:
        rows = [r for r in rows if (r.overtime_hours or 0.0) > 0.0]
    elif overtime_only is False:
        rows = [r for r in rows if (r.overtime_hours or 0.0) == 0.0]
    if search:
        needle = search.lower()
        rows = [
            r
            for r in rows
            if needle
            in " ".join(
                str(v or "")
                for v in (r.class_name, r.code, r.craft_class)
            ).lower()
        ]

    # --- sort: Nones always go last, regardless of direction.
    reverse = sort_dir == "desc"
    non_null = [r for r in rows if getattr(r, sort_by, None) is not None]
    null_rows = [r for r in rows if getattr(r, sort_by, None) is None]
    non_null.sort(key=lambda r: getattr(r, sort_by), reverse=reverse)
    rows = non_null + null_rows

    total = len(rows)
    start = (page - 1) * page_size
    items = rows[start:start + page_size]

    return TimecardListResponse(
        total=total,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        items=items,
    )


def get_timecard_detail(
    engine: Engine,
    tenant_id: str,
    class_name: str,
    *,
    band_pct: float = DEFAULT_VARIANCE_BAND_PCT,
) -> TimecardDetail | None:
    with engine.connect() as conn:
        a = conn.execute(
            text(
                """
                SELECT * FROM mart_fte_class_actual
                WHERE tenant_id = :tenant_id AND class_name = :class_name
                """
            ),
            {"tenant_id": tenant_id, "class_name": class_name},
        ).mappings().one_or_none()
        p = conn.execute(
            text(
                """
                SELECT * FROM mart_fte_class_projected
                WHERE tenant_id = :tenant_id AND class_name = :class_name
                """
            ),
            {"tenant_id": tenant_id, "class_name": class_name},
        ).mappings().one_or_none()

    if a is None and p is None:
        return None

    a_dict = dict(a) if a is not None else None
    p_dict = dict(p) if p is not None else None

    row = _build_row(a_dict, p_dict, band_pct)
    breakdown = _monthly_breakdown(a_dict, p_dict)

    return TimecardDetail(
        id=row.id,
        class_name=row.class_name,
        code=row.code,
        craft_class=row.craft_class,
        monthly_hours=row.monthly_hours,
        last_month_actuals=row.last_month_actuals,
        actual_avg_fte=row.actual_avg_fte,
        projected_avg_fte=row.projected_avg_fte,
        variance=row.variance,
        variance_pct=row.variance_pct,
        variance_status=row.variance_status,
        overtime_hours=row.overtime_hours,
        overtime_pct=row.overtime_pct,
        monthly_breakdown=breakdown,
    )


def get_insights(
    engine: Engine,
    tenant_id: str,
    *,
    band_pct: float = DEFAULT_VARIANCE_BAND_PCT,
    top_n: int = DEFAULT_TOP_N,
    now: datetime | None = None,
) -> TimecardInsights:
    """Precomputed analytics — the three items the Timecards screen needs.

    (1) Variance by job class (top over + top under).
    (2) Overtime % (top offenders).
    (3) Overhead ratio (single aggregate).
    """
    now_ = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    actual = _fetch_class_actual(engine, tenant_id)
    projected = _fetch_class_projected(engine, tenant_id)
    rows = _combine(actual, projected, band_pct)

    def _to_variance(r: TimecardListRow) -> VarianceByClass:
        return VarianceByClass(
            class_name=r.class_name,
            actual_avg_fte=r.actual_avg_fte,
            projected_avg_fte=r.projected_avg_fte,
            variance=r.variance,
            variance_pct=r.variance_pct,
            variance_status=r.variance_status,
        )

    over = sorted(
        (r for r in rows if r.variance_pct is not None and r.variance_pct > 0),
        key=lambda r: r.variance_pct,
        reverse=True,
    )[:top_n]
    under = sorted(
        (r for r in rows if r.variance_pct is not None and r.variance_pct < 0),
        key=lambda r: r.variance_pct,
    )[:top_n]

    overtime = sorted(
        (r for r in rows if (r.overtime_pct or 0.0) > 0.0),
        key=lambda r: r.overtime_pct,
        reverse=True,
    )[:top_n]

    direct_fte = sum(r.actual_avg_fte or 0.0 for r in rows)
    overhead_fte = _fetch_overhead_actual_total(engine, tenant_id)
    denom = direct_fte + overhead_fte
    ratio_pct = (overhead_fte / denom * 100.0) if denom else None

    return TimecardInsights(
        as_of=now_,
        variance_band_pct=band_pct,
        variance_over=[_to_variance(r) for r in over],
        variance_under=[_to_variance(r) for r in under],
        overtime_leaders=[
            OvertimeByClass(
                class_name=r.class_name,
                monthly_hours=r.monthly_hours,
                last_month_actuals=r.last_month_actuals,
                overtime_hours=r.overtime_hours,
                overtime_pct=r.overtime_pct,
            )
            for r in overtime
        ],
        overhead_ratio=OverheadRatio(
            overhead_fte=overhead_fte,
            direct_fte=direct_fte,
            ratio_pct=ratio_pct,
        ),
    )
