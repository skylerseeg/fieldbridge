"""Query layer for Market Intel reads.

All three analytics endpoints share a tenant-scoping pattern:
``WHERE bid_events.tenant_id IN (:caller_tenant, :shared_network_tenant)``.
The shared-network sentinel ID is loaded from ``app.core.seed`` — it's
where ``ITDPipeline`` writes ingested public bid abstracts.

Architecture: each function loads a parameterized SQL template from
``app/services/market_intel/analytics/*.sql`` (which does the filter +
join) and aggregates results in Python (median, quarter truncation,
top-N scope codes). This keeps queries cross-dialect — SQLite for
tests, Postgres for prod — without ``percentile_cont`` /
``date_trunc`` conditionals.
"""
from __future__ import annotations

import logging
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Iterable

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.seed import SHARED_NETWORK_TENANT_ID
from app.modules.market_intel.schema import (
    CalibrationPoint,
    CompetitorCurveRow,
    OpportunityRow,
)
from app.services.market_intel.analytics import load_sql

log = logging.getLogger("fieldbridge.market_intel")

# ~30 days/month is a coarse approximation for "months back" → cutoff.
# Calendar-month math would require dialect-specific date arithmetic;
# 30-day windows are good enough for this analytics surface.
_DAYS_PER_MONTH = 30


def _months_back_cutoff(months_back: int, *, today: date | None = None) -> date:
    today = today or date.today()
    return today - timedelta(days=months_back * _DAYS_PER_MONTH)


def _to_date(value: object) -> date | None:
    """Coerce a date-like value to ``date``.

    ``text()`` queries bypass the ORM type adapter, so SQLite returns
    DATE columns as ISO-8601 strings (`'2026-03-01'`) while Postgres
    returns proper ``date`` objects. Normalize either to ``date`` so
    downstream Python aggregation works on both backends.
    """
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _quarter_start(d: date) -> date:
    """Return the first day of the calendar quarter containing ``d``.
    Q1=Jan-1, Q2=Apr-1, Q3=Jul-1, Q4=Oct-1."""
    quarter_start_month = ((d.month - 1) // 3) * 3 + 1
    return date(d.year, quarter_start_month, 1)


# ---------------------------------------------------------------------------
# competitor_curves

async def get_competitor_curves(
    db: AsyncSession,
    *,
    states: list[str],
    months_back: int,
    min_bids: int,
    tenant_id: str,
) -> list[CompetitorCurveRow]:
    """Per-competitor pricing curves across the network.

    Loads ``competitor_curves.sql`` (one row per (bidder, event) with
    the per-event low amount) and aggregates by contractor in Python.
    Drops contractors with fewer than ``min_bids`` bids.

    Premium-over-low is computed per row as
    ``(bid_amount - low_amount) / low_amount`` and averaged. The low
    bidder's own row is included with premium=0.0 so the average
    reflects the contractor's full pricing personality, not just
    runner-up bids.
    """
    if not states:
        return []

    cutoff = _months_back_cutoff(months_back)
    sql = load_sql("competitor_curves")
    stmt = text(sql).bindparams(bindparam("state_codes", expanding=True))
    result = await db.execute(
        stmt,
        {
            "caller_tenant": tenant_id,
            "shared_network_tenant": SHARED_NETWORK_TENANT_ID,
            "state_codes": [s.upper() for s in states],
            "cutoff_date": cutoff,
        },
    )
    rows = list(result.mappings())

    # Group by contractor.
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        grouped[r["contractor_name"]].append(dict(r))

    out: list[CompetitorCurveRow] = []
    for name, bids in grouped.items():
        n = len(bids)
        if n < min_bids:
            continue
        ranks = [b["rank"] for b in bids if b["rank"] is not None]
        wins = sum(1 for b in bids if b["is_low_bidder"])
        premiums: list[float] = []
        for b in bids:
            low = b["low_amount"]
            amt = b["bid_amount"]
            if low and low > 0 and amt is not None:
                premiums.append((float(amt) - float(low)) / float(low))
        out.append(
            CompetitorCurveRow(
                contractor_name=name,
                bid_count=n,
                avg_premium_over_low=(
                    sum(premiums) / len(premiums) if premiums else 0.0
                ),
                median_rank=(statistics.median(ranks) if ranks else 0.0),
                win_rate=(wins / n) if n > 0 else 0.0,
            )
        )

    # Stable sort: most active competitors first, alphabetical tiebreak.
    out.sort(key=lambda r: (-r.bid_count, r.contractor_name))
    return out


# ---------------------------------------------------------------------------
# opportunity_gaps

async def get_opportunity_gaps(
    db: AsyncSession,
    *,
    bid_min: int,
    bid_max: int,
    months_back: int,
    tenant_id: str,
) -> list[OpportunityRow]:
    """County-level cells where similar-scope public work happens.

    SQL does the GROUP BY (state + county). ``top_scope_codes`` is
    returned as an empty list for now — ``bid_events.csi_codes`` is
    not populated until the ``email_bridge.csi_inference`` normalizer
    runs against scraped events (post-v1.5b). Frontend tolerates an
    empty array.
    """
    cutoff = _months_back_cutoff(months_back)
    sql = load_sql("opportunity_gaps")
    result = await db.execute(
        text(sql),
        {
            "caller_tenant": tenant_id,
            "shared_network_tenant": SHARED_NETWORK_TENANT_ID,
            "bid_min": bid_min,
            "bid_max": bid_max,
            "cutoff_date": cutoff,
        },
    )
    out: list[OpportunityRow] = []
    for r in result.mappings():
        out.append(
            OpportunityRow(
                state=r["state"],
                county=r["county"],
                missed_count=int(r["missed_count"]),
                avg_low_bid=float(r["avg_low_bid"] or 0.0),
                # Filled in post-v1.5b once csi_codes is populated.
                top_scope_codes=[],
            )
        )
    return out


# ---------------------------------------------------------------------------
# bid_calibration

async def get_bid_calibration(
    db: AsyncSession,
    *,
    contractor_name_match: str,
    tenant_id: str,
) -> list[CalibrationPoint]:
    """Per-quarter calibration of a contractor's own bids vs the low.

    Loads ``bid_calibration.sql`` (one row per matching bid joined
    with the per-event low amount) and groups by calendar quarter
    in Python. The quarter is keyed by ``_quarter_start(bid_open_date)``.

    The match pattern is wrapped in ``%`` wildcards so callers can
    pass plain substrings (e.g. ``"van con"`` matches ``"VanCon Inc."``).
    """
    sql = load_sql("bid_calibration")
    result = await db.execute(
        text(sql),
        {
            "caller_tenant": tenant_id,
            "shared_network_tenant": SHARED_NETWORK_TENANT_ID,
            "contractor_pattern": f"%{contractor_name_match}%",
        },
    )
    rows = list(result.mappings())
    if not rows:
        return []

    # Group by calendar quarter. Coerce date in case the dialect
    # returns ISO-8601 strings (SQLite via text() queries does this).
    by_quarter: dict[date, list[dict]] = defaultdict(list)
    for r in rows:
        d = _to_date(r["bid_open_date"])
        if d is None:
            continue
        q = _quarter_start(d)
        by_quarter[q].append(dict(r))

    out: list[CalibrationPoint] = []
    for q in sorted(by_quarter.keys()):
        bids = by_quarter[q]
        bids_submitted = len(bids)
        wins = sum(1 for b in bids if b["is_low_bidder"])
        ranks = [b["rank"] for b in bids if b["rank"] is not None]
        premiums: list[float] = []
        for b in bids:
            low = b["low_amount"]
            amt = b["bid_amount"]
            if low and low > 0 and amt is not None:
                premiums.append((float(amt) - float(low)) / float(low))
        avg_rank = sum(ranks) / len(ranks) if ranks else 0.0
        pct_above_low = (
            sum(premiums) / len(premiums) if premiums else None
        )
        out.append(
            CalibrationPoint(
                quarter=q,
                bids_submitted=bids_submitted,
                wins=wins,
                avg_rank=avg_rank,
                pct_above_low=pct_above_low,
            )
        )
    return out
