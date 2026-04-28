"""Jobs service — pure query functions against the SQLite marts.

Reads from three marts:
  - mart_job_wip             (41 rows; 1 per active contract)
  - mart_job_schedule        (44 rows; priority-ranked active schedule)
  - mart_estimate_variance   (302 rows; historical estimate vs actual)

Primary entity is the WIP row (financial truth). Jobs that appear
only in schedule — e.g. just-awarded work where WIP hasn't reported
yet — are included too, with financial fields left null.

Job-text matching is whitespace-insensitive: Vista stores the
description as ``' 2231. UDOT Bangerter...'`` with a leading space,
but URLs and filters shouldn't care. ``_strip_job_key`` is the
single place that normalization lives.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import Engine, text

from app.modules.jobs.schema import (
    BillingMetrics,
    BillingStatus,
    EstimateAccuracy,
    EstimateHistoryPoint,
    FinancialBreakdown,
    FinancialStatus,
    JobDetail,
    JobListResponse,
    JobListRow,
    JobMoneyRow,
    JobSummary,
    JobsInsights,
    ScheduleBreakdown,
    ScheduleStatus,
)


# --------------------------------------------------------------------------- #
# Tunables                                                                    #
# --------------------------------------------------------------------------- #

# proj_end falls within this many days of today -> at_risk.
DEFAULT_AT_RISK_DAYS = 30

# Margin pct (in percentage points, e.g. 2.0 = 2%) around 0 classified
# as breakeven. Wider than typical bid margin noise.
DEFAULT_BREAKEVEN_BAND_PCT = 2.0

# |over_under_billings| / total_contract tolerance (percentage points)
# classified as balanced. A 1% swing on a $20M contract is $200k —
# real but not alarming.
DEFAULT_BILLING_BALANCE_PCT = 2.0

# How many rows to return per top-N insight list.
DEFAULT_TOP_N = 10


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


SortField = Literal[
    "job", "priority", "proj_end", "percent_complete",
    "total_contract", "contract_cost_td", "est_gross_profit",
    "est_gross_profit_pct", "gross_profit_pct_td", "over_under_billings",
    "schedule_days_to_end",
]
SortDir = Literal["asc", "desc"]


def _strip_job_key(s: str | None) -> str:
    """Canonical job-id form: stripped, collapsed whitespace."""
    if s is None:
        return ""
    return " ".join(s.split())


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


def _schedule_status(
    proj_end: datetime | None,
    percent_complete: float | None,
    now: datetime,
    at_risk_days: int,
) -> tuple[int | None, ScheduleStatus]:
    """Return ``(days_to_end, status)``.

    A job with percent_complete >= 1.0 is never classified as late —
    it's done.
    """
    if proj_end is None:
        return None, ScheduleStatus.NO_SCHEDULE
    days = (proj_end - now).days
    complete = (percent_complete is not None and percent_complete >= 1.0)
    if days < 0 and not complete:
        return days, ScheduleStatus.LATE
    if days < 0 and complete:
        return days, ScheduleStatus.ON_SCHEDULE
    if days <= at_risk_days:
        return days, ScheduleStatus.AT_RISK
    return days, ScheduleStatus.ON_SCHEDULE


def _financial_status(
    est_gross_profit_pct: float | None,
    breakeven_band_pct: float,
) -> FinancialStatus:
    """Classify based on estimated gross profit % (fractional in WIP).

    Input is fractional (0.15 = 15%); the band is in percentage points,
    so we convert on the fly.
    """
    if est_gross_profit_pct is None:
        return FinancialStatus.UNKNOWN
    pct = est_gross_profit_pct * 100.0
    if pct > breakeven_band_pct:
        return FinancialStatus.PROFITABLE
    if pct < -breakeven_band_pct:
        return FinancialStatus.LOSS
    return FinancialStatus.BREAKEVEN


def _billing_status(
    over_under: float | None,
    total_contract: float | None,
    balance_pct: float,
) -> BillingStatus:
    """Classify over/under billing as a percent of contract value."""
    if over_under is None:
        return BillingStatus.UNKNOWN
    if not total_contract:
        return BillingStatus.UNKNOWN
    pct = abs(over_under) / total_contract * 100.0
    if pct <= balance_pct:
        return BillingStatus.BALANCED
    return (
        BillingStatus.OVER_BILLED
        if over_under > 0 else BillingStatus.UNDER_BILLED
    )


def _fetch_wip(engine: Engine, tenant_id: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT *
                FROM mart_job_wip
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
    return [dict(r) for r in rows]


def _fetch_schedule(engine: Engine, tenant_id: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT *
                FROM mart_job_schedule
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
    return [dict(r) for r in rows]


def _fetch_variance_for_job(
    engine: Engine, tenant_id: str, job_key: str,
) -> list[dict]:
    """Estimate-variance rows whose job_grouping matches the stripped key.

    We do the stripping in Python because SQLite's TRIM doesn't collapse
    internal whitespace and the mart stores the text verbatim.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT job_grouping, close_month, estimate, actual,
                       variance, percent
                FROM mart_estimate_variance
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
    return [
        dict(r) for r in rows
        if _strip_job_key(r["job_grouping"]) == job_key
    ]


def _fetch_all_variance(engine: Engine, tenant_id: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT job_grouping, close_month, estimate, actual,
                       variance, percent
                FROM mart_estimate_variance
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
    return [dict(r) for r in rows]


def _combine(
    wip_rows: list[dict],
    schedule_rows: list[dict],
    *,
    now: datetime,
    at_risk_days: int,
    breakeven_band_pct: float,
    billing_balance_pct: float,
) -> list[JobListRow]:
    """Full-outer-join WIP + schedule on stripped job key."""
    sched_by_key: dict[str, dict] = {}
    for s in schedule_rows:
        sched_by_key[_strip_job_key(s["job"])] = s

    seen: set[str] = set()
    out: list[JobListRow] = []

    for w in wip_rows:
        key = _strip_job_key(w["contract_job_description"])
        seen.add(key)
        s = sched_by_key.get(key)
        out.append(
            _build_row(
                key, w, s,
                now=now,
                at_risk_days=at_risk_days,
                breakeven_band_pct=breakeven_band_pct,
                billing_balance_pct=billing_balance_pct,
            )
        )

    for key, s in sched_by_key.items():
        if key in seen:
            continue
        out.append(
            _build_row(
                key, None, s,
                now=now,
                at_risk_days=at_risk_days,
                breakeven_band_pct=breakeven_band_pct,
                billing_balance_pct=billing_balance_pct,
            )
        )

    return out


def _build_row(
    key: str,
    wip: dict | None,
    sched: dict | None,
    *,
    now: datetime,
    at_risk_days: int,
    breakeven_band_pct: float,
    billing_balance_pct: float,
) -> JobListRow:
    total_contract = _f(wip.get("total_contract")) if wip else None
    contract_cost_td = _f(wip.get("contract_cost_td")) if wip else None
    est_total_cost = _f(wip.get("est_total_cost")) if wip else None
    est_gross_profit = _f(wip.get("est_gross_profit")) if wip else None
    est_gross_profit_pct = _f(wip.get("est_gross_profit_pct")) if wip else None
    gross_profit_pct_td = _f(wip.get("gross_profit_pct_td")) if wip else None
    percent_complete = _f(wip.get("percent_complete")) if wip else None
    billings_to_date = _f(wip.get("billings_to_date")) if wip else None
    over_under_billings = _f(wip.get("over_under_billings")) if wip else None

    priority = sched.get("priority") if sched else None
    start = _normalize_dt(sched.get("start")) if sched else None
    proj_end = _normalize_dt(sched.get("proj_end")) if sched else None
    milestone = _normalize_dt(sched.get("milestone")) if sched else None

    if sched is None:
        # WIP-only: we know the job, we just don't have a schedule row.
        # ``UNKNOWN`` is reserved for "no data at all" (unreachable from
        # ``_combine``); a missing schedule is ``NO_SCHEDULE``.
        schedule_status = ScheduleStatus.NO_SCHEDULE
        schedule_days_to_end: int | None = None
    else:
        schedule_days_to_end, schedule_status = _schedule_status(
            proj_end, percent_complete, now, at_risk_days,
        )

    financial_status = _financial_status(
        est_gross_profit_pct, breakeven_band_pct,
    )
    billing_status = _billing_status(
        over_under_billings, total_contract, billing_balance_pct,
    )

    return JobListRow(
        id=key,
        job=key,
        priority=priority,
        start=start,
        proj_end=proj_end,
        milestone=milestone,
        schedule_days_to_end=schedule_days_to_end,
        schedule_status=schedule_status,
        total_contract=total_contract,
        contract_cost_td=contract_cost_td,
        est_total_cost=est_total_cost,
        est_gross_profit=est_gross_profit,
        est_gross_profit_pct=est_gross_profit_pct,
        gross_profit_pct_td=gross_profit_pct_td,
        percent_complete=percent_complete,
        billings_to_date=billings_to_date,
        over_under_billings=over_under_billings,
        financial_status=financial_status,
        billing_status=billing_status,
    )


# --------------------------------------------------------------------------- #
# Public query API                                                            #
# --------------------------------------------------------------------------- #


def get_summary(
    engine: Engine,
    tenant_id: str,
    *,
    at_risk_days: int = DEFAULT_AT_RISK_DAYS,
    breakeven_band_pct: float = DEFAULT_BREAKEVEN_BAND_PCT,
    billing_balance_pct: float = DEFAULT_BILLING_BALANCE_PCT,
    now: datetime | None = None,
) -> JobSummary:
    now_ = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    wip = _fetch_wip(engine, tenant_id)
    schedule = _fetch_schedule(engine, tenant_id)
    rows = _combine(
        wip, schedule,
        now=now_,
        at_risk_days=at_risk_days,
        breakeven_band_pct=breakeven_band_pct,
        billing_balance_pct=billing_balance_pct,
    )

    total_contract_value = sum(r.total_contract or 0.0 for r in rows)
    total_cost_to_date = sum(r.contract_cost_td or 0.0 for r in rows)
    # contract_revenues_earned isn't exposed on list rows; reach back in.
    total_revenue_earned = sum(
        float(w["contract_revenues_earned"] or 0.0) for w in wip
    )
    total_gross_profit_td = sum(
        float(w["gross_profit_loss_td"] or 0.0) for w in wip
    )

    weighted_avg_margin_pct: float | None
    if total_revenue_earned:
        weighted_avg_margin_pct = (
            total_gross_profit_td / total_revenue_earned * 100.0
        )
    else:
        weighted_avg_margin_pct = None

    wip_rows = [r for r in rows if r.total_contract is not None]
    if wip_rows:
        avg_percent_complete = sum(
            r.percent_complete or 0.0 for r in wip_rows
        ) / len(wip_rows)
    else:
        avg_percent_complete = 0.0

    def _count(pred) -> int:
        return sum(1 for r in rows if pred(r))

    return JobSummary(
        total_jobs=len(rows),
        jobs_with_wip=sum(1 for r in rows if r.total_contract is not None),
        jobs_scheduled=sum(
            1 for r in rows
            if r.schedule_status not in (
                ScheduleStatus.UNKNOWN, ScheduleStatus.NO_SCHEDULE,
            )
        ),
        total_contract_value=total_contract_value,
        total_cost_to_date=total_cost_to_date,
        total_revenue_earned=total_revenue_earned,
        total_gross_profit_td=total_gross_profit_td,
        weighted_avg_margin_pct=weighted_avg_margin_pct,
        avg_percent_complete=avg_percent_complete,
        jobs_on_schedule=_count(
            lambda r: r.schedule_status is ScheduleStatus.ON_SCHEDULE
        ),
        jobs_at_risk=_count(
            lambda r: r.schedule_status is ScheduleStatus.AT_RISK
        ),
        jobs_late=_count(lambda r: r.schedule_status is ScheduleStatus.LATE),
        jobs_profitable=_count(
            lambda r: r.financial_status is FinancialStatus.PROFITABLE
        ),
        jobs_breakeven=_count(
            lambda r: r.financial_status is FinancialStatus.BREAKEVEN
        ),
        jobs_loss=_count(lambda r: r.financial_status is FinancialStatus.LOSS),
        jobs_over_billed=_count(
            lambda r: r.billing_status is BillingStatus.OVER_BILLED
        ),
        jobs_under_billed=_count(
            lambda r: r.billing_status is BillingStatus.UNDER_BILLED
        ),
        jobs_balanced=_count(
            lambda r: r.billing_status is BillingStatus.BALANCED
        ),
    )


def list_jobs(
    engine: Engine,
    tenant_id: str,
    *,
    page: int = 1,
    page_size: int = 25,
    sort_by: SortField = "priority",
    sort_dir: SortDir = "asc",
    schedule_status: ScheduleStatus | None = None,
    financial_status: FinancialStatus | None = None,
    billing_status: BillingStatus | None = None,
    search: str | None = None,
    at_risk_days: int = DEFAULT_AT_RISK_DAYS,
    breakeven_band_pct: float = DEFAULT_BREAKEVEN_BAND_PCT,
    billing_balance_pct: float = DEFAULT_BILLING_BALANCE_PCT,
    now: datetime | None = None,
) -> JobListResponse:
    """Paginated, filterable, sortable job list."""
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 500:
        page_size = 25
    if sort_dir not in ("asc", "desc"):
        sort_dir = "asc"

    now_ = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    wip = _fetch_wip(engine, tenant_id)
    schedule = _fetch_schedule(engine, tenant_id)
    rows = _combine(
        wip, schedule,
        now=now_,
        at_risk_days=at_risk_days,
        breakeven_band_pct=breakeven_band_pct,
        billing_balance_pct=billing_balance_pct,
    )

    if schedule_status is not None:
        rows = [r for r in rows if r.schedule_status is schedule_status]
    if financial_status is not None:
        rows = [r for r in rows if r.financial_status is financial_status]
    if billing_status is not None:
        rows = [r for r in rows if r.billing_status is billing_status]
    if search:
        needle = search.lower()
        rows = [r for r in rows if needle in r.job.lower()]

    # Nones always last, regardless of direction.
    reverse = sort_dir == "desc"
    non_null = [r for r in rows if getattr(r, sort_by, None) is not None]
    null_rows = [r for r in rows if getattr(r, sort_by, None) is None]
    non_null.sort(key=lambda r: getattr(r, sort_by), reverse=reverse)
    rows = non_null + null_rows

    total = len(rows)
    start = (page - 1) * page_size
    items = rows[start:start + page_size]

    return JobListResponse(
        total=total,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        items=items,
    )


def get_job_detail(
    engine: Engine,
    tenant_id: str,
    job_id: str,
    *,
    at_risk_days: int = DEFAULT_AT_RISK_DAYS,
    breakeven_band_pct: float = DEFAULT_BREAKEVEN_BAND_PCT,
    billing_balance_pct: float = DEFAULT_BILLING_BALANCE_PCT,
    now: datetime | None = None,
) -> JobDetail | None:
    """Detail view — WIP + schedule + full estimate history."""
    now_ = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    key = _strip_job_key(job_id)

    # Locate the WIP row (if any) by stripped key.
    wip = _fetch_wip(engine, tenant_id)
    w = next(
        (
            r for r in wip
            if _strip_job_key(r["contract_job_description"]) == key
        ),
        None,
    )

    schedule = _fetch_schedule(engine, tenant_id)
    s = next(
        (r for r in schedule if _strip_job_key(r["job"]) == key),
        None,
    )

    if w is None and s is None:
        return None

    row = _build_row(
        key, w, s,
        now=now_,
        at_risk_days=at_risk_days,
        breakeven_band_pct=breakeven_band_pct,
        billing_balance_pct=billing_balance_pct,
    )

    # History — already stripped/filtered by _fetch_variance_for_job.
    hist_rows = _fetch_variance_for_job(engine, tenant_id, key)
    history: list[EstimateHistoryPoint] = []
    for h in hist_rows:
        estimate = _f(h.get("estimate"))
        actual = _f(h.get("actual"))
        variance = _f(h.get("variance"))
        if variance is None and estimate is not None and actual is not None:
            variance = estimate - actual
        variance_pct: float | None
        if estimate and variance is not None:
            variance_pct = variance / estimate * 100.0
        else:
            variance_pct = None
        history.append(
            EstimateHistoryPoint(
                close_month=_normalize_dt(h["close_month"]),
                estimate=estimate,
                actual=actual,
                variance=variance,
                variance_pct=variance_pct,
            )
        )
    history.sort(
        key=lambda p: (p.close_month is None, p.close_month or datetime.min),
    )

    return JobDetail(
        id=row.id,
        job=row.job,
        priority=row.priority,
        start=row.start,
        proj_end=row.proj_end,
        milestone=row.milestone,
        schedule_days_to_end=row.schedule_days_to_end,
        schedule_status=row.schedule_status,
        reason=s.get("reason") if s is not None else None,
        total_contract=row.total_contract,
        contract_cost_td=row.contract_cost_td,
        est_cost_to_complete=_f(w.get("est_cost_to_complete")) if w else None,
        est_total_cost=row.est_total_cost,
        est_gross_profit=row.est_gross_profit,
        est_gross_profit_pct=row.est_gross_profit_pct,
        percent_complete=row.percent_complete,
        gain_fade_from_prior_mth=(
            _f(w.get("gain_fade_from_prior_mth")) if w else None
        ),
        billings_to_date=row.billings_to_date,
        over_under_billings=row.over_under_billings,
        contract_revenues_earned=(
            _f(w.get("contract_revenues_earned")) if w else None
        ),
        gross_profit_loss_td=(
            _f(w.get("gross_profit_loss_td")) if w else None
        ),
        gross_profit_pct_td=row.gross_profit_pct_td,
        financial_status=row.financial_status,
        billing_status=row.billing_status,
        estimate_history=history,
    )


def get_insights(
    engine: Engine,
    tenant_id: str,
    *,
    at_risk_days: int = DEFAULT_AT_RISK_DAYS,
    breakeven_band_pct: float = DEFAULT_BREAKEVEN_BAND_PCT,
    billing_balance_pct: float = DEFAULT_BILLING_BALANCE_PCT,
    top_n: int = DEFAULT_TOP_N,
    now: datetime | None = None,
) -> JobsInsights:
    """Precomputed analytics — the three screens a PM scans daily.

    (1) Schedule health breakdown.
    (2) Financial health breakdown + top profit/loss lists.
    (3) Billing metrics + top over/under-billed.
    (4) Bonus: rolling estimate accuracy from historical variance.
    """
    now_ = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    wip = _fetch_wip(engine, tenant_id)
    schedule = _fetch_schedule(engine, tenant_id)
    rows = _combine(
        wip, schedule,
        now=now_,
        at_risk_days=at_risk_days,
        breakeven_band_pct=breakeven_band_pct,
        billing_balance_pct=billing_balance_pct,
    )

    sched_counts = ScheduleBreakdown(
        on_schedule=sum(
            1 for r in rows if r.schedule_status is ScheduleStatus.ON_SCHEDULE
        ),
        at_risk=sum(
            1 for r in rows if r.schedule_status is ScheduleStatus.AT_RISK
        ),
        late=sum(1 for r in rows if r.schedule_status is ScheduleStatus.LATE),
        no_schedule=sum(
            1 for r in rows if r.schedule_status is ScheduleStatus.NO_SCHEDULE
        ),
        unknown=sum(
            1 for r in rows if r.schedule_status is ScheduleStatus.UNKNOWN
        ),
    )

    fin_counts = FinancialBreakdown(
        profitable=sum(
            1 for r in rows if r.financial_status is FinancialStatus.PROFITABLE
        ),
        breakeven=sum(
            1 for r in rows if r.financial_status is FinancialStatus.BREAKEVEN
        ),
        loss=sum(
            1 for r in rows if r.financial_status is FinancialStatus.LOSS
        ),
        unknown=sum(
            1 for r in rows if r.financial_status is FinancialStatus.UNKNOWN
        ),
    )

    over_bills = [
        r for r in rows
        if r.billing_status is BillingStatus.OVER_BILLED
        and r.over_under_billings is not None
    ]
    under_bills = [
        r for r in rows
        if r.billing_status is BillingStatus.UNDER_BILLED
        and r.over_under_billings is not None
    ]
    total_over = sum(r.over_under_billings for r in over_bills)
    total_under = sum(-r.over_under_billings for r in under_bills)

    billing_metrics = BillingMetrics(
        over_billed_count=len(over_bills),
        balanced_count=sum(
            1 for r in rows if r.billing_status is BillingStatus.BALANCED
        ),
        under_billed_count=len(under_bills),
        unknown_count=sum(
            1 for r in rows if r.billing_status is BillingStatus.UNKNOWN
        ),
        total_over_billed=total_over,
        total_under_billed=total_under,
    )

    # Estimate accuracy: use mart_estimate_variance (all rows).
    var_rows = _fetch_all_variance(engine, tenant_id)
    pcts: list[float] = []
    for v in var_rows:
        est = _f(v.get("estimate"))
        actual = _f(v.get("actual"))
        variance = _f(v.get("variance"))
        # Prefer explicit variance column, fall back to est - actual.
        if variance is None and est is not None and actual is not None:
            variance = est - actual
        if est and variance is not None:
            pcts.append(variance / est * 100.0)

    if pcts:
        avg_variance_pct = sum(pcts) / len(pcts)
        avg_abs_variance_pct = sum(abs(p) for p in pcts) / len(pcts)
    else:
        avg_variance_pct = None
        avg_abs_variance_pct = None

    estimate_accuracy = EstimateAccuracy(
        samples=len(var_rows),
        jobs_tracked=len({_strip_job_key(v["job_grouping"]) for v in var_rows}),
        avg_variance_pct=avg_variance_pct,
        avg_abs_variance_pct=avg_abs_variance_pct,
    )

    # Top lists.
    def _money_row(r: JobListRow, value: float) -> JobMoneyRow:
        return JobMoneyRow(
            id=r.id,
            job=r.job,
            value=value,
            percent_complete=r.percent_complete,
            total_contract=r.total_contract,
        )

    with_profit = [r for r in rows if r.est_gross_profit is not None]
    top_profit = sorted(
        (r for r in with_profit if r.est_gross_profit > 0),
        key=lambda r: r.est_gross_profit,
        reverse=True,
    )[:top_n]
    top_loss = sorted(
        (r for r in with_profit if r.est_gross_profit < 0),
        key=lambda r: r.est_gross_profit,
    )[:top_n]

    top_over_billed = sorted(over_bills, key=lambda r: r.over_under_billings,
                             reverse=True)[:top_n]
    top_under_billed = sorted(under_bills,
                              key=lambda r: r.over_under_billings)[:top_n]

    return JobsInsights(
        as_of=now_,
        at_risk_days=at_risk_days,
        breakeven_band_pct=breakeven_band_pct,
        billing_balance_pct=billing_balance_pct,
        schedule_breakdown=sched_counts,
        financial_breakdown=fin_counts,
        billing_metrics=billing_metrics,
        estimate_accuracy=estimate_accuracy,
        top_profit=[_money_row(r, r.est_gross_profit) for r in top_profit],
        top_loss=[_money_row(r, r.est_gross_profit) for r in top_loss],
        top_over_billed=[
            _money_row(r, r.over_under_billings) for r in top_over_billed
        ],
        top_under_billed=[
            _money_row(r, r.over_under_billings) for r in top_under_billed
        ],
    )
