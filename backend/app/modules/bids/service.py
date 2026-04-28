"""Bids service — pure query functions against the SQLite marts.

Reads two marts:
  - ``mart_bids_history``  — one row per (job, bid_date) bid event.
  - ``mart_bids_outlook``  — one row per pipeline entry (summary only).

``mart_bids_history`` is the rich source: for each bid VanCon
considered, it records whether they submitted (``was_bid``), their
bid amount (``vancon``), the competitor range (``low`` / ``high``),
their finishing rank, and up to 17 wide competitor-bid slots. This
module derives three orthogonal classifications per bid — outcome
(won / lost / no_bid / unknown), margin tier, and competition tier —
and rolls them up across estimator / bid_type / county segments.

Helpers (``_bid_id``, ``_outcome``, ``_margin_tier``,
``_competition_tier``, ``_percent_over``) are pure and unit-testable.
"""
from __future__ import annotations

import hashlib
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy import Engine, text

from app.modules.bids.schema import (
    BidDetail,
    BidListResponse,
    BidListRow,
    BidOutcome,
    BidsInsights,
    BidsSummary,
    BigWinRow,
    CompetitionTier,
    CompetitionTierBreakdown,
    CompetitorBidSlot,
    MarginTier,
    MarginTierBreakdown,
    NearMissRow,
    OutcomeBreakdown,
    RiskFlagFrequencyRow,
    WinRateBySegmentRow,
)


# --------------------------------------------------------------------------- #
# Tunables                                                                    #
# --------------------------------------------------------------------------- #


# Margin banding on ``percent_over`` (VanCon/low - 1).
DEFAULT_CLOSE_MARGIN_MAX = 0.03       # <= 3% → CLOSE
DEFAULT_MODERATE_MARGIN_MAX = 0.10    # <= 10% → MODERATE; else WIDE.

# Competition-tier thresholds on ``number_bidders``.
DEFAULT_LIGHT_BIDDERS_MAX = 3      # 2..3 → LIGHT
DEFAULT_TYPICAL_BIDDERS_MAX = 6    # 4..6 → TYPICAL; >6 → CROWDED

# How many rows to return per top-N insight list.
DEFAULT_TOP_N = 10

# Columns treated as boolean risk flags (store 0.0/1.0 floats in the mart).
RISK_FLAG_COLUMNS: tuple[str, ...] = (
    "deep",
    "traffic_control",
    "dewatering",
    "bypass_pumping",
    "tight_time_frame",
    "tight_job_site",
    "haul_off",
    "insurance_requirement",
)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


SortField = Literal[
    "bid_date",
    "job",
    "vancon",
    "low",
    "rank",
    "number_bidders",
    "percent_over",
    "lost_by",
]
SortDir = Literal["asc", "desc"]


def _bid_id(job: str | None, bid_date) -> str:
    """Stable 12-hex-char ID for a (job, bid_date) pair."""
    job_part = (job or "").strip()
    if isinstance(bid_date, datetime):
        date_part = bid_date.isoformat()
    else:
        date_part = str(bid_date or "")
    digest = hashlib.md5(f"{job_part}|{date_part}".encode("utf-8")).hexdigest()
    return digest[:12]


def _to_bool(val) -> bool | None:
    """Coerce mart-stored ints/floats/bools to a plain bool. None-preserving."""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val > 0
    return None


def _truthy_flag(val) -> bool:
    """Risk-flag columns store 0.0/1.0 floats; treat >= 1 as flagged."""
    if val is None:
        return False
    try:
        return float(val) >= 1.0
    except (TypeError, ValueError):
        return False


def _percent_over(vancon: float | None, low: float | None) -> float | None:
    """``vancon / low - 1``. None when either input is missing or ``low <= 0``."""
    if vancon is None or low is None or low <= 0:
        return None
    return vancon / low - 1.0


def _outcome(was_bid, rank) -> BidOutcome:
    if not _to_bool(was_bid):
        return BidOutcome.NO_BID
    if rank is None:
        return BidOutcome.UNKNOWN
    try:
        r = int(rank)
    except (TypeError, ValueError):
        return BidOutcome.UNKNOWN
    return BidOutcome.WON if r == 1 else BidOutcome.LOST


def _margin_tier(
    outcome: BidOutcome,
    percent_over: float | None,
    *,
    close_max: float = DEFAULT_CLOSE_MARGIN_MAX,
    moderate_max: float = DEFAULT_MODERATE_MARGIN_MAX,
) -> MarginTier:
    if outcome is BidOutcome.WON:
        return MarginTier.WINNER
    # Margin tier only carries meaning for LOST bids — NO_BID / UNKNOWN
    # outcomes don't have a "how close did we come" story even if a
    # percent_over value is present on the row.
    if outcome is not BidOutcome.LOST:
        return MarginTier.UNKNOWN
    if percent_over is None:
        return MarginTier.UNKNOWN
    if percent_over <= close_max:
        return MarginTier.CLOSE
    if percent_over <= moderate_max:
        return MarginTier.MODERATE
    return MarginTier.WIDE


def _competition_tier(
    number_bidders,
    *,
    light_max: int = DEFAULT_LIGHT_BIDDERS_MAX,
    typical_max: int = DEFAULT_TYPICAL_BIDDERS_MAX,
) -> CompetitionTier:
    if number_bidders is None:
        return CompetitionTier.UNKNOWN
    try:
        n = int(number_bidders)
    except (TypeError, ValueError):
        return CompetitionTier.UNKNOWN
    if n <= 0:
        return CompetitionTier.UNKNOWN
    if n == 1:
        return CompetitionTier.SOLO
    if n <= light_max:
        return CompetitionTier.LIGHT
    if n <= typical_max:
        return CompetitionTier.TYPICAL
    return CompetitionTier.CROWDED


def _parse_bid_date(val) -> datetime | None:
    """SQLite stores DateTime columns as ISO strings; Postgres as datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(str(val))
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Rollup                                                                      #
# --------------------------------------------------------------------------- #


@dataclass
class _EnrichedBid:
    row: dict
    id: str
    job: str
    bid_date: datetime | None

    was_bid: bool
    vancon: float | None
    low: float | None
    high: float | None
    rank: int | None
    number_bidders: int | None
    lost_by: float | None
    percent_over: float | None

    outcome: BidOutcome
    margin_tier: MarginTier
    competition_tier: CompetitionTier

    @property
    def list_row(self) -> BidListRow:
        r = self.row
        return BidListRow(
            id=self.id,
            job=self.job,
            bid_date=self.bid_date,
            was_bid=self.was_bid,
            owner=r.get("owner"),
            bid_type=r.get("bid_type"),
            county=r.get("county"),
            estimator=r.get("estimator"),
            vancon=self.vancon,
            low=self.low,
            high=self.high,
            engineer_estimate=r.get("engineer_estimate"),
            rank=self.rank,
            number_bidders=self.number_bidders,
            lost_by=self.lost_by,
            percent_over=self.percent_over,
            outcome=self.outcome,
            margin_tier=self.margin_tier,
            competition_tier=self.competition_tier,
        )


def _enrich(
    row: dict,
    *,
    close_max: float = DEFAULT_CLOSE_MARGIN_MAX,
    moderate_max: float = DEFAULT_MODERATE_MARGIN_MAX,
    light_max: int = DEFAULT_LIGHT_BIDDERS_MAX,
    typical_max: int = DEFAULT_TYPICAL_BIDDERS_MAX,
) -> _EnrichedBid:
    job = row.get("job") or ""
    bid_date = _parse_bid_date(row.get("bid_date"))
    was_bid = bool(_to_bool(row.get("was_bid")))
    vancon = row.get("vancon")
    low = row.get("low")
    high = row.get("high")

    rank_raw = row.get("rank")
    rank = int(rank_raw) if rank_raw is not None else None

    nb_raw = row.get("number_bidders")
    try:
        number_bidders = int(nb_raw) if nb_raw is not None else None
    except (TypeError, ValueError):
        number_bidders = None

    lost_by = row.get("lost_by")
    pct = row.get("percent_over")
    percent_over = float(pct) if pct is not None else _percent_over(vancon, low)

    outcome = _outcome(row.get("was_bid"), rank)
    margin = _margin_tier(
        outcome, percent_over,
        close_max=close_max, moderate_max=moderate_max,
    )
    competition = _competition_tier(
        number_bidders,
        light_max=light_max, typical_max=typical_max,
    )

    return _EnrichedBid(
        row=row,
        id=_bid_id(job, bid_date or row.get("bid_date")),
        job=job,
        bid_date=bid_date,
        was_bid=was_bid,
        vancon=vancon,
        low=low,
        high=high,
        rank=rank,
        number_bidders=number_bidders,
        lost_by=lost_by,
        percent_over=percent_over,
        outcome=outcome,
        margin_tier=margin,
        competition_tier=competition,
    )


# --------------------------------------------------------------------------- #
# SQL fetchers                                                                #
# --------------------------------------------------------------------------- #


_BASE_COLS = [
    "job", "bid_date", "was_bid", "owner", "bid_type", "county",
    "estimator", "completion_date", "labor_cost_factor",
    "avg_mark_up_pct", "mark_up", "overhead_add_on", "equip_op_exp",
    "co_equip", "high", "low", "vancon", "rank", "won", "lost_by",
    "percent_over", "number_bidders", "pq", "plan_source", "db_wages",
    "engineer_estimate", "notice_to_proceed_date",
]
_RISK_COLS = list(RISK_FLAG_COLUMNS)
_COMPETITOR_COLS = [
    f"bid_{i}_{suffix}"
    for i in range(1, 18)
    for suffix in ("comp", "amt", "won")
]


def _fetch_all(engine: Engine, tenant_id: str) -> list[dict]:
    cols = _BASE_COLS + _RISK_COLS + _COMPETITOR_COLS
    col_sql = ", ".join(cols)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT {col_sql} FROM mart_bids_history "
                "WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
    return [dict(r) for r in rows]


def _fetch_outlook_count(engine: Engine, tenant_id: str) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT COUNT(*) FROM mart_bids_outlook "
                "WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        ).scalar_one() or 0


# --------------------------------------------------------------------------- #
# Public query API                                                            #
# --------------------------------------------------------------------------- #


def get_summary(engine: Engine, tenant_id: str) -> BidsSummary:
    raws = _fetch_all(engine, tenant_id)
    enriched = [_enrich(r) for r in raws]

    total_bids = len(enriched)
    submitted = [e for e in enriched if e.was_bid]
    bids_submitted = len(submitted)
    no_bids = total_bids - bids_submitted
    bids_won = sum(1 for e in submitted if e.outcome is BidOutcome.WON)
    bids_lost = sum(1 for e in submitted if e.outcome is BidOutcome.LOST)
    unknown = sum(1 for e in submitted if e.outcome is BidOutcome.UNKNOWN)

    win_rate = bids_won / bids_submitted if bids_submitted else 0.0

    vancon_amounts = [e.vancon for e in submitted if e.vancon is not None]
    total_vancon_bid = sum(vancon_amounts)
    avg_vancon_bid = (
        total_vancon_bid / len(vancon_amounts) if vancon_amounts else 0.0
    )
    total_vancon_won = sum(
        e.vancon for e in submitted
        if e.outcome is BidOutcome.WON and e.vancon is not None
    )

    bidder_counts = [
        e.number_bidders for e in submitted
        if e.number_bidders is not None
    ]
    median_bidders = (
        statistics.median(bidder_counts) if bidder_counts else None
    )

    distinct_estimators = len({
        e.row.get("estimator") for e in enriched
        if e.row.get("estimator")
    })
    distinct_owners = len({
        e.row.get("owner") for e in enriched if e.row.get("owner")
    })
    distinct_counties = len({
        e.row.get("county") for e in enriched if e.row.get("county")
    })
    distinct_bid_types = len({
        e.row.get("bid_type") for e in enriched if e.row.get("bid_type")
    })

    return BidsSummary(
        total_bids=total_bids,
        bids_submitted=bids_submitted,
        no_bids=no_bids,
        bids_won=bids_won,
        bids_lost=bids_lost,
        unknown_outcome=unknown,
        win_rate=round(win_rate, 4),
        total_vancon_bid_amount=round(total_vancon_bid, 2),
        total_vancon_won_amount=round(total_vancon_won, 2),
        avg_vancon_bid=round(avg_vancon_bid, 2),
        median_number_bidders=median_bidders,
        distinct_estimators=distinct_estimators,
        distinct_owners=distinct_owners,
        distinct_counties=distinct_counties,
        distinct_bid_types=distinct_bid_types,
        outlook_count=_fetch_outlook_count(engine, tenant_id),
    )


def list_bids(
    engine: Engine,
    tenant_id: str,
    *,
    page: int = 1,
    page_size: int = 25,
    sort_by: SortField = "bid_date",
    sort_dir: SortDir = "desc",
    outcome: BidOutcome | None = None,
    margin_tier: MarginTier | None = None,
    competition_tier: CompetitionTier | None = None,
    bid_type: str | None = None,
    estimator: str | None = None,
    county: str | None = None,
    search: str | None = None,
    close_max: float = DEFAULT_CLOSE_MARGIN_MAX,
    moderate_max: float = DEFAULT_MODERATE_MARGIN_MAX,
    light_max: int = DEFAULT_LIGHT_BIDDERS_MAX,
    typical_max: int = DEFAULT_TYPICAL_BIDDERS_MAX,
) -> BidListResponse:
    """Paginated, filterable, sortable list of bids."""
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 500:
        page_size = 25
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"

    raws = _fetch_all(engine, tenant_id)
    enriched = [
        _enrich(
            r,
            close_max=close_max, moderate_max=moderate_max,
            light_max=light_max, typical_max=typical_max,
        )
        for r in raws
    ]
    rows = [e.list_row for e in enriched]

    if outcome is not None:
        rows = [r for r in rows if r.outcome is outcome]
    if margin_tier is not None:
        rows = [r for r in rows if r.margin_tier is margin_tier]
    if competition_tier is not None:
        rows = [r for r in rows if r.competition_tier is competition_tier]
    if bid_type is not None:
        needle = bid_type.strip()
        if needle:
            rows = [r for r in rows if r.bid_type == needle]
    if estimator is not None:
        needle = estimator.strip()
        if needle:
            rows = [r for r in rows if r.estimator == needle]
    if county is not None:
        needle = county.strip()
        if needle:
            rows = [r for r in rows if r.county == needle]
    if search:
        needle = search.lower()
        rows = [
            r for r in rows
            if needle in r.job.lower()
            or (r.owner and needle in r.owner.lower())
            or (r.estimator and needle in r.estimator.lower())
            or (r.county and needle in r.county.lower())
        ]

    reverse = sort_dir == "desc"

    def _key(r: BidListRow):
        val = getattr(r, sort_by, None)
        if sort_by == "job" and isinstance(val, str):
            return val.lower()
        return val

    non_null = [r for r in rows if getattr(r, sort_by, None) is not None]
    null_rows = [r for r in rows if getattr(r, sort_by, None) is None]
    non_null.sort(key=_key, reverse=reverse)
    rows = non_null + null_rows

    total = len(rows)
    start = (page - 1) * page_size
    items = rows[start:start + page_size]

    return BidListResponse(
        total=total,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        items=items,
    )


def _competitor_slots(row: dict) -> list[CompetitorBidSlot]:
    out: list[CompetitorBidSlot] = []
    for i in range(1, 18):
        comp = row.get(f"bid_{i}_comp")
        amt = row.get(f"bid_{i}_amt")
        won = row.get(f"bid_{i}_won")
        if comp is None and amt is None and won is None:
            continue
        out.append(
            CompetitorBidSlot(
                slot=i,
                competitor=comp,
                amount=amt,
                won_amount=won,
            )
        )
    out.sort(
        key=lambda s: (s.amount is None, s.amount if s.amount is not None else 0.0)
    )
    return out


def get_bid_detail(
    engine: Engine,
    tenant_id: str,
    bid_id: str,
    *,
    close_max: float = DEFAULT_CLOSE_MARGIN_MAX,
    moderate_max: float = DEFAULT_MODERATE_MARGIN_MAX,
    light_max: int = DEFAULT_LIGHT_BIDDERS_MAX,
    typical_max: int = DEFAULT_TYPICAL_BIDDERS_MAX,
) -> BidDetail | None:
    """Fetch a single bid by its synthetic ``bid_id``."""
    key = (bid_id or "").strip().lower()
    if not key:
        return None

    for raw in _fetch_all(engine, tenant_id):
        e = _enrich(
            raw,
            close_max=close_max, moderate_max=moderate_max,
            light_max=light_max, typical_max=typical_max,
        )
        if e.id == key:
            row = e.row
            risk_flags = [
                col for col in RISK_FLAG_COLUMNS
                if _truthy_flag(row.get(col))
            ]
            return BidDetail(
                id=e.id,
                job=e.job,
                bid_date=e.bid_date,
                was_bid=e.was_bid,
                owner=row.get("owner"),
                bid_type=row.get("bid_type"),
                county=row.get("county"),
                estimator=row.get("estimator"),
                vancon=e.vancon,
                low=e.low,
                high=e.high,
                engineer_estimate=row.get("engineer_estimate"),
                rank=e.rank,
                number_bidders=e.number_bidders,
                lost_by=e.lost_by,
                percent_over=e.percent_over,
                outcome=e.outcome,
                margin_tier=e.margin_tier,
                competition_tier=e.competition_tier,
                labor_cost_factor=row.get("labor_cost_factor"),
                avg_mark_up_pct=row.get("avg_mark_up_pct"),
                mark_up=row.get("mark_up"),
                overhead_add_on=row.get("overhead_add_on"),
                equip_op_exp=row.get("equip_op_exp"),
                co_equip=row.get("co_equip"),
                completion_date=_parse_bid_date(row.get("completion_date")),
                notice_to_proceed_date=_parse_bid_date(
                    row.get("notice_to_proceed_date")
                ),
                pq=_to_bool(row.get("pq")),
                db_wages=_to_bool(row.get("db_wages")),
                plan_source=row.get("plan_source"),
                risk_flags=risk_flags,
                competitors=_competitor_slots(row),
            )
    return None


def _segment_rollup(
    enriched: list[_EnrichedBid],
    *,
    key: str,
    top_n: int,
) -> list[WinRateBySegmentRow]:
    """Group submitted bids by ``key`` column, return top-N by submissions."""
    buckets: dict[str, dict] = {}
    for e in enriched:
        if not e.was_bid:
            continue
        seg = e.row.get(key)
        if seg is None:
            continue
        slot = buckets.setdefault(
            seg,
            {"submitted": 0, "won": 0, "lost": 0, "unknown": 0, "won_amt": 0.0},
        )
        slot["submitted"] += 1
        if e.outcome is BidOutcome.WON:
            slot["won"] += 1
            if e.vancon is not None:
                slot["won_amt"] += e.vancon
        elif e.outcome is BidOutcome.LOST:
            slot["lost"] += 1
        else:
            slot["unknown"] += 1

    sorted_items = sorted(
        buckets.items(), key=lambda kv: kv[1]["submitted"], reverse=True,
    )[:top_n]
    return [
        WinRateBySegmentRow(
            segment=seg,
            submitted=slot["submitted"],
            won=slot["won"],
            lost=slot["lost"],
            unknown=slot["unknown"],
            win_rate=round(
                slot["won"] / slot["submitted"], 4,
            ) if slot["submitted"] else 0.0,
            total_vancon_won_amount=round(slot["won_amt"], 2),
        )
        for seg, slot in sorted_items
    ]


def get_insights(
    engine: Engine,
    tenant_id: str,
    *,
    top_n: int = DEFAULT_TOP_N,
    close_max: float = DEFAULT_CLOSE_MARGIN_MAX,
    moderate_max: float = DEFAULT_MODERATE_MARGIN_MAX,
    light_max: int = DEFAULT_LIGHT_BIDDERS_MAX,
    typical_max: int = DEFAULT_TYPICAL_BIDDERS_MAX,
) -> BidsInsights:
    """Precomputed analytics for the bids dashboard."""
    raws = _fetch_all(engine, tenant_id)
    enriched = [
        _enrich(
            r,
            close_max=close_max, moderate_max=moderate_max,
            light_max=light_max, typical_max=typical_max,
        )
        for r in raws
    ]

    outcome_counts = Counter(e.outcome for e in enriched)
    outcome_breakdown = OutcomeBreakdown(
        won=outcome_counts.get(BidOutcome.WON, 0),
        lost=outcome_counts.get(BidOutcome.LOST, 0),
        no_bid=outcome_counts.get(BidOutcome.NO_BID, 0),
        unknown=outcome_counts.get(BidOutcome.UNKNOWN, 0),
    )

    # Margin tier — count only submitted bids; NO_BID isn't a margin outcome.
    submitted = [e for e in enriched if e.was_bid]
    margin_counts = Counter(e.margin_tier for e in submitted)
    margin_breakdown = MarginTierBreakdown(
        winner=margin_counts.get(MarginTier.WINNER, 0),
        close=margin_counts.get(MarginTier.CLOSE, 0),
        moderate=margin_counts.get(MarginTier.MODERATE, 0),
        wide=margin_counts.get(MarginTier.WIDE, 0),
        unknown=margin_counts.get(MarginTier.UNKNOWN, 0),
    )

    competition_counts = Counter(e.competition_tier for e in submitted)
    competition_breakdown = CompetitionTierBreakdown(
        solo=competition_counts.get(CompetitionTier.SOLO, 0),
        light=competition_counts.get(CompetitionTier.LIGHT, 0),
        typical=competition_counts.get(CompetitionTier.TYPICAL, 0),
        crowded=competition_counts.get(CompetitionTier.CROWDED, 0),
        unknown=competition_counts.get(CompetitionTier.UNKNOWN, 0),
    )

    win_rate_by_bid_type = _segment_rollup(
        enriched, key="bid_type", top_n=top_n,
    )
    win_rate_by_estimator = _segment_rollup(
        enriched, key="estimator", top_n=top_n,
    )
    win_rate_by_county = _segment_rollup(
        enriched, key="county", top_n=top_n,
    )

    # Near-misses: submitted losses with known lost_by, lowest first.
    near_miss_candidates = [
        e for e in submitted
        if e.outcome is BidOutcome.LOST and e.lost_by is not None
    ]
    near_miss_candidates.sort(key=lambda e: e.lost_by)
    near_misses = [
        NearMissRow(
            id=e.id,
            job=e.job,
            bid_date=e.bid_date,
            vancon=e.vancon,
            low=e.low,
            lost_by=e.lost_by,
            percent_over=e.percent_over,
            estimator=e.row.get("estimator"),
        )
        for e in near_miss_candidates[:top_n]
    ]

    # Big wins by VanCon bid value.
    wins = [
        e for e in submitted
        if e.outcome is BidOutcome.WON and e.vancon is not None
    ]
    wins.sort(key=lambda e: e.vancon or 0.0, reverse=True)
    big_wins = [
        BigWinRow(
            id=e.id,
            job=e.job,
            bid_date=e.bid_date,
            vancon=e.vancon or 0.0,
            owner=e.row.get("owner"),
            bid_type=e.row.get("bid_type"),
            estimator=e.row.get("estimator"),
        )
        for e in wins[:top_n]
    ]

    # Risk-flag frequency + win-rate among flagged submissions.
    risk_rows: list[RiskFlagFrequencyRow] = []
    for flag in RISK_FLAG_COLUMNS:
        flagged = [e for e in enriched if _truthy_flag(e.row.get(flag))]
        flagged_submitted = [e for e in flagged if e.was_bid]
        won = sum(
            1 for e in flagged_submitted if e.outcome is BidOutcome.WON
        )
        win_rate = (
            won / len(flagged_submitted) if flagged_submitted else 0.0
        )
        risk_rows.append(
            RiskFlagFrequencyRow(
                flag=flag,
                count=len(flagged),
                win_rate=round(win_rate, 4),
            )
        )
    # Sort most-frequent first so the UI shows biggest flags at the top.
    risk_rows.sort(key=lambda r: r.count, reverse=True)

    return BidsInsights(
        outcome_breakdown=outcome_breakdown,
        margin_tier_breakdown=margin_breakdown,
        competition_tier_breakdown=competition_breakdown,
        win_rate_by_bid_type=win_rate_by_bid_type,
        win_rate_by_estimator=win_rate_by_estimator,
        win_rate_by_county=win_rate_by_county,
        near_misses=near_misses,
        big_wins=big_wins,
        risk_flag_frequency=risk_rows,
    )
