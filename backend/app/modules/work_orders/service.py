"""Work-orders service — pure query functions against the SQLite mart.

Same contract as ``app.modules.equipment.service``: every function takes
an ``Engine`` + ``tenant_id`` and returns plain Pydantic models. No
FastAPI types leak in, no global state — so the tests inject a seeded
engine and assert on return values directly.

Reads from:
  - mart_work_orders  (Vista emwo shape; see excel_marts/work_orders/schema.py)

Vista status/priority codes are translated in one place here so the
mapping change (if Vista adds, say, 'P' for Parts-Wait) is a single-line
edit.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import Engine, text

from app.modules.work_orders.schema import (
    CostVsBudget,
    StatusCounts,
    WorkOrderDetail,
    WorkOrderInsights,
    WorkOrderListResponse,
    WorkOrderListRow,
    WorkOrderPriority,
    WorkOrderStatus,
    WorkOrderSummary,
)


# --------------------------------------------------------------------------- #
# Tunables                                                                    #
# --------------------------------------------------------------------------- #

# A WO is overdue when it's still open past this many days. Matches the
# equipment module's STALE_DAYS — aligned so one calendar mental model
# applies across both screens.
DEFAULT_OVERDUE_DAYS = 30


# --------------------------------------------------------------------------- #
# Vista code -> enum mapping                                                  #
# --------------------------------------------------------------------------- #


_STATUS_MAP: dict[str, WorkOrderStatus] = {
    "O": WorkOrderStatus.OPEN,
    "C": WorkOrderStatus.CLOSED,
    "H": WorkOrderStatus.HOLD,
}
_PRIORITY_MAP: dict[str, WorkOrderPriority] = {
    "1": WorkOrderPriority.CRITICAL,
    "2": WorkOrderPriority.HIGH,
    "3": WorkOrderPriority.NORMAL,
}


def _status(code: str | None) -> WorkOrderStatus:
    if code is None:
        return WorkOrderStatus.UNKNOWN
    return _STATUS_MAP.get(code.strip().upper(), WorkOrderStatus.UNKNOWN)


def _priority(code: str | None) -> WorkOrderPriority:
    if code is None:
        return WorkOrderPriority.UNKNOWN
    return _PRIORITY_MAP.get(str(code).strip(), WorkOrderPriority.UNKNOWN)


def _reverse_status(s: WorkOrderStatus) -> str | None:
    """Used by filter predicates to push status back into the DB code."""
    for code, val in _STATUS_MAP.items():
        if val is s:
            return code
    return None


def _reverse_priority(p: WorkOrderPriority) -> str | None:
    for code, val in _PRIORITY_MAP.items():
        if val is p:
            return code
    return None


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


SortField = Literal[
    "work_order", "equipment", "status", "priority",
    "open_date", "closed_date", "age_days", "total_cost",
]
SortDir = Literal["asc", "desc"]

_DB_SORT_COLUMNS: set[str] = {
    "work_order", "equipment", "status", "priority",
    "open_date", "closed_date", "total_cost",
}


def _normalize_dt(v) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


def _age_days(
    open_date: datetime | None,
    closed_date: datetime | None,
    status: WorkOrderStatus,
    now: datetime,
) -> int | None:
    """Age in whole days.

    For open/hold WOs, ``age = now - open_date``.
    For closed WOs, ``age = closed_date - open_date`` (lifespan).
    Returns None if we don't have enough dates.
    """
    if open_date is None:
        return None
    if status is WorkOrderStatus.CLOSED and closed_date is not None:
        return max(0, (closed_date - open_date).days)
    return max(0, (now - open_date).days)


def _is_overdue(
    status: WorkOrderStatus, age: int | None, overdue_days: int,
) -> bool:
    return (
        status in (WorkOrderStatus.OPEN, WorkOrderStatus.HOLD)
        and age is not None
        and age > overdue_days
    )


def _fetch_all(engine: Engine, tenant_id: str) -> list[dict]:
    """One pass over the mart. All endpoints aggregate in Python — the
    WO volume per tenant is a few thousand rows at most, and centralizing
    the read lets status/age derivations live in exactly one place."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT work_order, equipment, description, status, priority,
                       requested_by, open_date, closed_date, mechanic,
                       labor_hours, parts_cost, total_cost, job_number,
                       estimated_hours, estimated_cost
                FROM mart_work_orders
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Public query API                                                            #
# --------------------------------------------------------------------------- #


def get_summary(
    engine: Engine,
    tenant_id: str,
    *,
    overdue_days: int = DEFAULT_OVERDUE_DAYS,
    now: datetime | None = None,
) -> WorkOrderSummary:
    now = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    rows = _fetch_all(engine, tenant_id)

    total = len(rows)
    open_count = closed_count = hold_count = overdue_count = 0
    open_ages: list[int] = []
    total_cost = 0.0
    total_budget = 0.0

    for r in rows:
        status = _status(r.get("status"))
        open_dt = _normalize_dt(r.get("open_date"))
        closed_dt = _normalize_dt(r.get("closed_date"))
        age = _age_days(open_dt, closed_dt, status, now)

        if status is WorkOrderStatus.OPEN:
            open_count += 1
            if age is not None:
                open_ages.append(age)
        elif status is WorkOrderStatus.CLOSED:
            closed_count += 1
        elif status is WorkOrderStatus.HOLD:
            hold_count += 1

        if _is_overdue(status, age, overdue_days):
            overdue_count += 1

        if r.get("total_cost") is not None:
            total_cost += float(r["total_cost"])
        if r.get("estimated_cost") is not None:
            total_budget += float(r["estimated_cost"])

    avg_age = (sum(open_ages) / len(open_ages)) if open_ages else 0.0

    return WorkOrderSummary(
        total_work_orders=total,
        open_count=open_count,
        closed_count=closed_count,
        hold_count=hold_count,
        overdue_count=overdue_count,
        overdue_threshold_days=overdue_days,
        avg_age_days_open=avg_age,
        total_cost_to_date=total_cost,
        total_budget=total_budget,
    )


def list_work_orders(
    engine: Engine,
    tenant_id: str,
    *,
    page: int = 1,
    page_size: int = 25,
    sort_by: SortField = "open_date",
    sort_dir: SortDir = "desc",
    status: WorkOrderStatus | None = None,
    priority: WorkOrderPriority | None = None,
    equipment: str | None = None,
    mechanic: str | None = None,
    overdue: bool | None = None,
    search: str | None = None,
    overdue_days: int = DEFAULT_OVERDUE_DAYS,
    now: datetime | None = None,
) -> WorkOrderListResponse:
    """Paginated, filtered, sorted list.

    Filtering + sorting happens in Python after a single read so the
    derived columns (``age_days``, ``overdue``) can participate. The WO
    table is small enough that per-tenant that's fine.
    """
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 500:
        page_size = 25
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"

    now = (now or datetime.now(timezone.utc)).replace(tzinfo=None)

    raw = _fetch_all(engine, tenant_id)
    enriched: list[WorkOrderListRow] = []

    for r in raw:
        st = _status(r.get("status"))
        pr = _priority(r.get("priority"))
        open_dt = _normalize_dt(r.get("open_date"))
        closed_dt = _normalize_dt(r.get("closed_date"))
        age = _age_days(open_dt, closed_dt, st, now)
        is_overdue = _is_overdue(st, age, overdue_days)

        # Filters
        if status is not None and st is not status:
            continue
        if priority is not None and pr is not priority:
            continue
        if equipment and (r.get("equipment") or "").lower() != equipment.lower():
            continue
        if mechanic and (r.get("mechanic") or "").lower() != mechanic.lower():
            continue
        if overdue is True and not is_overdue:
            continue
        if overdue is False and is_overdue:
            continue
        if search:
            needle = search.lower()
            haystack = " ".join(
                str(r.get(k) or "") for k in (
                    "work_order", "equipment", "description", "mechanic",
                    "requested_by", "job_number",
                )
            ).lower()
            if needle not in haystack:
                continue

        enriched.append(
            WorkOrderListRow(
                id=str(r["work_order"]),
                work_order=str(r["work_order"]),
                equipment=r.get("equipment"),
                description=r.get("description"),
                status=st,
                priority=pr,
                open_date=open_dt,
                closed_date=closed_dt,
                age_days=age,
                overdue=is_overdue,
                mechanic=r.get("mechanic"),
                total_cost=(
                    float(r["total_cost"]) if r.get("total_cost") is not None else None
                ),
                estimated_cost=(
                    float(r["estimated_cost"])
                    if r.get("estimated_cost") is not None else None
                ),
            )
        )

    reverse = sort_dir == "desc"

    # None values should always sort LAST, regardless of direction. We can't
    # express that with a single key-tuple when ``reverse=True`` flips the
    # ``v is None`` flag too. Split, sort non-nulls, then append nulls.
    non_null = [r for r in enriched if getattr(r, sort_by, None) is not None]
    null_rows = [r for r in enriched if getattr(r, sort_by, None) is None]
    non_null.sort(key=lambda r: getattr(r, sort_by), reverse=reverse)
    enriched = non_null + null_rows

    total = len(enriched)
    start = (page - 1) * page_size
    items = enriched[start:start + page_size]

    return WorkOrderListResponse(
        total=total,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        items=items,
    )


def get_work_order_detail(
    engine: Engine,
    tenant_id: str,
    work_order: str,
    *,
    overdue_days: int = DEFAULT_OVERDUE_DAYS,
    now: datetime | None = None,
) -> WorkOrderDetail | None:
    now = (now or datetime.now(timezone.utc)).replace(tzinfo=None)

    with engine.connect() as conn:
        r = conn.execute(
            text(
                """
                SELECT work_order, equipment, description, status, priority,
                       requested_by, open_date, closed_date, mechanic,
                       labor_hours, parts_cost, total_cost, job_number,
                       estimated_hours, estimated_cost
                FROM mart_work_orders
                WHERE tenant_id = :tenant_id AND work_order = :work_order
                """
            ),
            {"tenant_id": tenant_id, "work_order": work_order},
        ).mappings().one_or_none()

    if r is None:
        return None

    st = _status(r.get("status"))
    pr = _priority(r.get("priority"))
    open_dt = _normalize_dt(r.get("open_date"))
    closed_dt = _normalize_dt(r.get("closed_date"))
    age = _age_days(open_dt, closed_dt, st, now)
    is_overdue = _is_overdue(st, age, overdue_days)

    total_cost = (
        float(r["total_cost"]) if r.get("total_cost") is not None else None
    )
    budget = (
        float(r["estimated_cost"])
        if r.get("estimated_cost") is not None else None
    )
    variance = (
        total_cost - budget
        if total_cost is not None and budget is not None else None
    )
    variance_pct = (
        (variance / budget * 100.0)
        if variance is not None and budget not in (None, 0) else None
    )

    return WorkOrderDetail(
        id=str(r["work_order"]),
        work_order=str(r["work_order"]),
        equipment=r.get("equipment"),
        description=r.get("description"),
        status=st,
        priority=pr,
        requested_by=r.get("requested_by"),
        mechanic=r.get("mechanic"),
        job_number=r.get("job_number"),
        open_date=open_dt,
        closed_date=closed_dt,
        age_days=age,
        overdue=is_overdue,
        labor_hours=(
            float(r["labor_hours"]) if r.get("labor_hours") is not None else None
        ),
        estimated_hours=(
            float(r["estimated_hours"])
            if r.get("estimated_hours") is not None else None
        ),
        parts_cost=(
            float(r["parts_cost"]) if r.get("parts_cost") is not None else None
        ),
        total_cost=total_cost,
        estimated_cost=budget,
        cost_variance=variance,
        cost_variance_pct=variance_pct,
    )


def get_insights(
    engine: Engine,
    tenant_id: str,
    *,
    overdue_days: int = DEFAULT_OVERDUE_DAYS,
    now: datetime | None = None,
) -> WorkOrderInsights:
    """Precomputed analytics — the four items the Work Orders screen needs.

    (1) Open count by status.
    (2) Avg age (days) of open WOs.
    (3) Overdue count (open/hold past overdue_days).
    (4) Cost-to-date vs budget.
    """
    now_ = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    rows = _fetch_all(engine, tenant_id)

    open_n = closed_n = hold_n = unknown_n = overdue_n = 0
    open_ages: list[int] = []
    cost_to_date = 0.0
    budget = 0.0

    for r in rows:
        st = _status(r.get("status"))
        open_dt = _normalize_dt(r.get("open_date"))
        closed_dt = _normalize_dt(r.get("closed_date"))
        age = _age_days(open_dt, closed_dt, st, now_)

        if st is WorkOrderStatus.OPEN:
            open_n += 1
            if age is not None:
                open_ages.append(age)
        elif st is WorkOrderStatus.CLOSED:
            closed_n += 1
        elif st is WorkOrderStatus.HOLD:
            hold_n += 1
        else:
            unknown_n += 1

        if _is_overdue(st, age, overdue_days):
            overdue_n += 1

        if r.get("total_cost") is not None:
            cost_to_date += float(r["total_cost"])
        if r.get("estimated_cost") is not None:
            budget += float(r["estimated_cost"])

    avg_age = (sum(open_ages) / len(open_ages)) if open_ages else 0.0
    variance = cost_to_date - budget
    variance_pct = (variance / budget * 100.0) if budget else None

    return WorkOrderInsights(
        as_of=now_,
        overdue_threshold_days=overdue_days,
        status_counts=StatusCounts(
            open=open_n, closed=closed_n, hold=hold_n, unknown=unknown_n,
        ),
        avg_age_days_open=avg_age,
        overdue_count=overdue_n,
        cost_vs_budget=CostVsBudget(
            cost_to_date=cost_to_date,
            budget=budget,
            variance=variance,
            variance_pct=variance_pct,
        ),
    )
