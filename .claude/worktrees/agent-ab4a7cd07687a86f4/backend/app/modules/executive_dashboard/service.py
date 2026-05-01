"""Executive dashboard service — pure cross-mart aggregation.

This module deliberately reads *only* from marts the per-module screens
already use, so a CFO who drills into Equipment / Jobs / Bids never
sees a different number from what the dashboard headline showed.

Tables touched:

  * ``mart_job_wip``               — financial pulse + attention list
  * ``mart_job_schedule``          — operations pulse (at-risk / late counts)
  * ``mart_equipment_utilization`` — operations pulse (30-day activity)
  * ``mart_bids_outlook``          — pipeline pulse
  * ``mart_bids_history``          — pipeline pulse (YTD win rate)
  * ``mart_proposals``             — pipeline pulse (outstanding count)
  * ``mart_vendors``               — roster pulse
  * ``mart_asset_barcodes``        — roster pulse
  * ``mart_estimate_variance``     — trend (monthly actual/estimate)

Every function takes ``Engine`` + ``tenant_id`` so tests inject a
fixture engine. No ORM mappers — raw text() against the marts (the
schemas are stable; see ``docs/data_mapping.md``).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import Engine, text

from app.modules.executive_dashboard.schema import (
    AttentionItem,
    AttentionKind,
    ExecutiveAttention,
    ExecutiveSummary,
    ExecutiveTrend,
    FinancialPulse,
    MonthlyRevenuePoint,
    OperationsPulse,
    PipelinePulse,
    RosterPulse,
)


# --------------------------------------------------------------------------- #
# Tunables                                                                    #
# --------------------------------------------------------------------------- #

# proj_end within this many days of "now" -> at_risk.
AT_RISK_DAYS = 30

# Margin band (percentage points) classifying a job as profitable
# vs. loss. Mirrors jobs.service.DEFAULT_BREAKEVEN_BAND_PCT.
LOSS_BAND_PCT = 2.0

# |over_under_billings| / total_contract tolerance (percentage points)
# above which we flag a job to the attention list.
BILLING_BAND_PCT = 2.0

# How many trailing months of revenue trend to expose.
TREND_MONTHS = 12


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _f(v) -> float | None:
    """Cast to float, swallowing None / non-numerics."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _normalize_dt(v) -> datetime | None:
    """SQLite stores DateTime as ISO strings; coerce back to datetime."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None


def _strip_job_key(s: str | None) -> str:
    """Canonical job-id form: stripped, collapsed whitespace.

    Same normalization the jobs module uses, so the executive list
    deep-links cleanly into ``/jobs/{job_id}``.
    """
    if s is None:
        return ""
    return " ".join(s.split())


def _safe_div(a: float, b: float) -> float:
    """0.0 when b == 0, else a/b. Used for weighted averages and rates."""
    return a / b if b else 0.0


# --------------------------------------------------------------------------- #
# Block builders                                                              #
# --------------------------------------------------------------------------- #


def _financial_pulse(engine: Engine, tenant_id: str) -> FinancialPulse:
    """Roll up mart_job_wip in one query.

    The status counts (over/under/balanced) are computed in Python
    rather than SQL because the band test is the same one the jobs
    module applies — easier to keep consistent if it lives in one
    language only.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT total_contract,
                       contract_cost_td,
                       contract_revenues_earned,
                       est_gross_profit,
                       over_under_billings
                FROM mart_job_wip
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()

    total_contract = 0.0
    total_cost = 0.0
    total_earned = 0.0
    total_gp = 0.0
    total_oub = 0.0
    over = under = balanced = 0

    for r in rows:
        contract = _f(r["total_contract"]) or 0.0
        total_contract += contract
        total_cost += _f(r["contract_cost_td"]) or 0.0
        total_earned += _f(r["contract_revenues_earned"]) or 0.0
        total_gp += _f(r["est_gross_profit"]) or 0.0

        oub = _f(r["over_under_billings"])
        if oub is None or contract == 0.0:
            balanced += 1
            continue
        total_oub += oub
        pct = abs(oub) / contract * 100.0
        if pct <= BILLING_BAND_PCT:
            balanced += 1
        elif oub > 0:
            over += 1
        else:
            under += 1

    return FinancialPulse(
        active_jobs=len(rows),
        total_contract_value=total_contract,
        total_revenue_earned=total_earned,
        total_cost_to_date=total_cost,
        total_estimated_gross_profit=total_gp,
        weighted_gross_profit_pct=_safe_div(total_gp, total_contract),
        total_over_under_billings=total_oub,
        over_billed_jobs=over,
        under_billed_jobs=under,
        balanced_jobs=balanced,
    )


def _operations_pulse(
    engine: Engine, tenant_id: str, *, now: datetime,
) -> OperationsPulse:
    """Schedule risk + 30-day equipment activity."""
    now_naive = now.replace(tzinfo=None)
    window_start = (now_naive - timedelta(days=30)).isoformat()

    with engine.connect() as conn:
        sched_rows = conn.execute(
            text(
                """
                SELECT job, proj_end
                FROM mart_job_schedule
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()

        truck_rows = conn.execute(
            text(
                """
                SELECT COUNT(DISTINCT truck) AS distinct_trucks
                FROM mart_equipment_utilization
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).one()

        tickets_30d, revenue_30d = conn.execute(
            text(
                """
                SELECT COUNT(*) AS tickets,
                       COALESCE(SUM(extended_price), 0) AS revenue
                FROM mart_equipment_utilization
                WHERE tenant_id = :tenant_id
                  AND ticket_date >= :window_start
                """
            ),
            {"tenant_id": tenant_id, "window_start": window_start},
        ).one()

    # We need percent_complete to gate "late" — pull it from WIP and
    # match by stripped job key. Do it once here rather than rolling it
    # into _financial_pulse so the two pulses stay independently
    # testable.
    wip_complete: dict[str, float] = {}
    with engine.connect() as conn:
        for r in conn.execute(
            text(
                """
                SELECT contract_job_description, percent_complete
                FROM mart_job_wip
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all():
            key = _strip_job_key(r["contract_job_description"])
            pct = _f(r["percent_complete"])
            if pct is not None:
                wip_complete[key] = pct

    at_risk = late = 0
    seen_jobs: set[str] = set()
    for s in sched_rows:
        seen_jobs.add(_strip_job_key(s["job"]))
        proj_end = _normalize_dt(s["proj_end"])
        if proj_end is None:
            continue
        days = (proj_end - now_naive).days
        complete = wip_complete.get(_strip_job_key(s["job"]), 0.0) >= 1.0
        if days < 0 and not complete:
            late += 1
        elif 0 <= days <= AT_RISK_DAYS and not complete:
            at_risk += 1

    return OperationsPulse(
        scheduled_jobs=len(seen_jobs),
        jobs_at_risk=at_risk,
        jobs_late=late,
        total_equipment=int(truck_rows[0] or 0),
        equipment_tickets_30d=int(tickets_30d or 0),
        equipment_revenue_30d=float(revenue_30d or 0.0),
    )


def _pipeline_pulse(
    engine: Engine, tenant_id: str, *, now: datetime,
) -> PipelinePulse:
    """Bid + proposal pipeline."""
    now_naive = now.replace(tzinfo=None)
    horizon = (now_naive + timedelta(days=30)).isoformat()
    year_start = datetime(now_naive.year, 1, 1).isoformat()

    with engine.connect() as conn:
        outlook_total, ready_for_review, upcoming_30d = conn.execute(
            text(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN ready_for_review THEN 1 ELSE 0 END)
                        AS ready,
                    SUM(CASE
                        WHEN (bid_date IS NOT NULL
                              AND bid_date BETWEEN :now AND :horizon)
                          OR (anticipated_bid_date IS NOT NULL
                              AND anticipated_bid_date
                                  BETWEEN :now AND :horizon)
                        THEN 1 ELSE 0
                    END) AS upcoming
                FROM mart_bids_outlook
                WHERE tenant_id = :tenant_id
                """
            ),
            {
                "tenant_id": tenant_id,
                "now": now_naive.isoformat(),
                "horizon": horizon,
            },
        ).one()

        # YTD bid history. ``won`` is a float in the source mart (often 0/1
        # encoded); ``> 0`` covers both 1.0 and partials.
        submitted_ytd, won_ytd = conn.execute(
            text(
                """
                SELECT
                    COUNT(*) AS submitted,
                    SUM(CASE WHEN won IS NOT NULL AND won > 0
                             THEN 1 ELSE 0 END) AS won
                FROM mart_bids_history
                WHERE tenant_id = :tenant_id
                  AND bid_date >= :year_start
                """
            ),
            {"tenant_id": tenant_id, "year_start": year_start},
        ).one()

        proposals = conn.execute(
            text(
                "SELECT COUNT(*) FROM mart_proposals "
                "WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        ).scalar()

    submitted_ytd = int(submitted_ytd or 0)
    won_ytd = int(won_ytd or 0)
    return PipelinePulse(
        bids_in_pipeline=int(outlook_total or 0),
        bids_ready_for_review=int(ready_for_review or 0),
        upcoming_bids_30d=int(upcoming_30d or 0),
        bids_submitted_ytd=submitted_ytd,
        bids_won_ytd=won_ytd,
        win_rate_ytd=_safe_div(float(won_ytd), float(submitted_ytd)),
        proposals_outstanding=int(proposals or 0),
    )


def _roster_pulse(engine: Engine, tenant_id: str) -> RosterPulse:
    """Vendor / asset master counts."""
    with engine.connect() as conn:
        vendors = conn.execute(
            text(
                "SELECT COUNT(*) FROM mart_vendors "
                "WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        ).scalar()

        total_assets, retired = conn.execute(
            text(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN retired_date IS NOT NULL
                                THEN 1 ELSE 0 END) AS retired
                FROM mart_asset_barcodes
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).one()

    return RosterPulse(
        total_vendors=int(vendors or 0),
        total_assets=int(total_assets or 0),
        retired_assets=int(retired or 0),
    )


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #


def get_summary(
    engine: Engine,
    tenant_id: str,
    *,
    now: datetime | None = None,
) -> ExecutiveSummary:
    """Top-of-page KPI tile rollup. One round-trip from the frontend."""
    now = now or datetime.now(timezone.utc)
    return ExecutiveSummary(
        as_of=now,
        financial=_financial_pulse(engine, tenant_id),
        operations=_operations_pulse(engine, tenant_id, now=now),
        pipeline=_pipeline_pulse(engine, tenant_id, now=now),
        roster=_roster_pulse(engine, tenant_id),
    )


def get_attention(
    engine: Engine,
    tenant_id: str,
    *,
    now: datetime | None = None,
    top_n: int = 10,
) -> ExecutiveAttention:
    """Top-N flagged jobs across margin / schedule / billing axes.

    Each WIP+schedule row may produce zero, one, or several
    ``AttentionItem``s — a job that's both losing money and late lands
    on the list twice. The frontend can collapse by ``job_id`` if it
    wants, but the default is "show me everything that needs eyes".
    """
    now = now or datetime.now(timezone.utc)
    now_naive = now.replace(tzinfo=None)

    with engine.connect() as conn:
        wip_rows = conn.execute(
            text(
                """
                SELECT contract_job_description,
                       total_contract,
                       est_gross_profit,
                       est_gross_profit_pct,
                       percent_complete,
                       over_under_billings
                FROM mart_job_wip
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()

        sched_rows = conn.execute(
            text(
                """
                SELECT job, proj_end
                FROM mart_job_schedule
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()

    # Full outer join on stripped job key so jobs that are scheduled
    # but haven't reported WIP yet (just-awarded work) still get
    # late/at-risk-flagged. Conversely, a WIP-only job (no schedule)
    # gets margin/billing checks but no schedule axis.
    sched_by_key: dict[str, datetime | None] = {}
    for s in sched_rows:
        sched_by_key[_strip_job_key(s["job"])] = _normalize_dt(s["proj_end"])

    by_key: dict[str, dict] = {}
    for w in wip_rows:
        key = _strip_job_key(w["contract_job_description"])
        by_key[key] = {
            "raw": w["contract_job_description"],
            "wip": w,
        }
    for s in sched_rows:
        key = _strip_job_key(s["job"])
        if key not in by_key:
            by_key[key] = {"raw": s["job"], "wip": None}

    items: list[AttentionItem] = []
    for job_id, payload in by_key.items():
        raw = payload["raw"]
        w = payload["wip"]
        contract = _f(w["total_contract"]) if w else None
        oub = _f(w["over_under_billings"]) if w else None
        margin = _f(w["est_gross_profit_pct"]) if w else None
        gp = _f(w["est_gross_profit"]) if w else None
        pct_complete = (_f(w["percent_complete"]) or 0.0) if w else 0.0
        proj_end = sched_by_key.get(job_id)

        # 1) Loss — large negative GP ratio, ranked by absolute GP $.
        if margin is not None and (margin * 100.0) < -LOSS_BAND_PCT:
            severity = abs(gp) if gp is not None else abs(margin) * 100.0
            items.append(
                AttentionItem(
                    job_id=job_id,
                    job=raw,
                    kind=AttentionKind.LOSS,
                    severity=severity,
                    detail=(
                        f"Projected loss "
                        f"{margin * 100.0:.1f}% margin"
                        + (f" (${gp:,.0f})" if gp is not None else "")
                    ),
                    total_contract=contract,
                    est_gross_profit_pct=margin,
                    over_under_billings=oub,
                )
            )

        # 2) Schedule — late or at-risk. Ranked by days past / days remaining.
        if proj_end is not None and pct_complete < 1.0:
            days = (proj_end - now_naive).days
            if days < 0:
                items.append(
                    AttentionItem(
                        job_id=job_id,
                        job=raw,
                        kind=AttentionKind.LATE,
                        severity=float(-days),
                        detail=f"{-days} days past projected end",
                        total_contract=contract,
                        est_gross_profit_pct=margin,
                        days_to_proj_end=days,
                    )
                )
            elif days <= AT_RISK_DAYS:
                items.append(
                    AttentionItem(
                        job_id=job_id,
                        job=raw,
                        kind=AttentionKind.AT_RISK,
                        # Smaller days = more severe; invert.
                        severity=float(AT_RISK_DAYS - days),
                        detail=f"Projected end in {days} days",
                        total_contract=contract,
                        est_gross_profit_pct=margin,
                        days_to_proj_end=days,
                    )
                )

        # 3) Billing — outside band. Severity = absolute over/under $.
        if (
            oub is not None
            and contract is not None
            and contract > 0
            and abs(oub) / contract * 100.0 > BILLING_BAND_PCT
        ):
            kind = (
                AttentionKind.OVER_BILLED if oub > 0
                else AttentionKind.UNDER_BILLED
            )
            pct = abs(oub) / contract * 100.0
            items.append(
                AttentionItem(
                    job_id=job_id,
                    job=raw,
                    kind=kind,
                    severity=abs(oub),
                    detail=(
                        f"${abs(oub):,.0f} "
                        f"{'over' if oub > 0 else 'under'}-billed "
                        f"({pct:.1f}% of contract)"
                    ),
                    total_contract=contract,
                    over_under_billings=oub,
                )
            )

    items.sort(key=lambda i: i.severity, reverse=True)
    return ExecutiveAttention(as_of=now, items=items[:top_n])


def get_trend(
    engine: Engine,
    tenant_id: str,
    *,
    now: datetime | None = None,
    months: int = TREND_MONTHS,
) -> ExecutiveTrend:
    """Trailing-N-months estimate vs. actual for the sparkline.

    Aggregated in Python because SQLite's ``strftime`` is sufficient
    but we'd still need a left-join against a generated month series
    to fill empty months — easier to bucket here.
    """
    now = now or datetime.now(timezone.utc)
    now_naive = now.replace(tzinfo=None)

    # Build the [oldest, ..., current] window of (year, month) pairs
    # so empty months still show on the sparkline as zero.
    window: list[tuple[int, int]] = []
    cursor_year, cursor_month = now_naive.year, now_naive.month
    for _ in range(months):
        window.append((cursor_year, cursor_month))
        cursor_month -= 1
        if cursor_month == 0:
            cursor_month = 12
            cursor_year -= 1
    window.reverse()
    window_set = set(window)

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT close_month, estimate, actual
                FROM mart_estimate_variance
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()

    bucketed: dict[tuple[int, int], tuple[float, float]] = defaultdict(
        lambda: (0.0, 0.0),
    )
    for r in rows:
        cm = _normalize_dt(r["close_month"])
        if cm is None:
            continue
        key = (cm.year, cm.month)
        if key not in window_set:
            continue
        est = _f(r["estimate"]) or 0.0
        act = _f(r["actual"]) or 0.0
        cur_est, cur_act = bucketed[key]
        bucketed[key] = (cur_est + est, cur_act + act)

    return ExecutiveTrend(
        as_of=now,
        months=[
            MonthlyRevenuePoint(
                month=f"{y:04d}-{m:02d}",
                estimate=bucketed[(y, m)][0],
                actual=bucketed[(y, m)][1],
            )
            for (y, m) in window
        ],
    )
