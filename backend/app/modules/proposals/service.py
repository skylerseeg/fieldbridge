"""Proposals service — pure query functions against the SQLite marts.

Reads two marts:
  - ``mart_proposals``           — one row per (job, owner, bid_type).
  - ``mart_proposal_line_items`` — per-competitor fee/schedule rows;
    currently keyed by ``_row_hash`` only, not yet joinable to a
    specific proposal.

This module classifies each proposal by:

  1. **BidTypeCategory** — keyword bucketing of the free-form
     ``bid_type`` (pressurized / structures / concrete / earthwork /
     other).
  2. **GeographyTier** — parse two-letter state from ``county``, bucket
     as in-state (== ``primary_state``) vs. out-of-state vs. unknown.

Line-item statistics (competitor frequency, per-fee count / min / max
/ average) are computed tenant-wide and surfaced in ``/summary`` +
``/insights``.

Helpers (``_proposal_id``, ``_parse_state``, ``_bid_type_category``,
``_geography_tier``) are pure and unit-testable.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Engine, text

from app.modules.proposals.schema import (
    BidTypeCategory,
    BidTypeCategoryBreakdown,
    CompetitorFrequencyRow,
    FeeStatsRow,
    GeographyTier,
    GeographyTierBreakdown,
    ProposalDetail,
    ProposalListResponse,
    ProposalListRow,
    ProposalsInsights,
    ProposalsSummary,
    SegmentCountRow,
)


# --------------------------------------------------------------------------- #
# Tunables                                                                    #
# --------------------------------------------------------------------------- #


# Two-letter state code treated as "home". Override per-request to
# support tenants based outside Utah.
DEFAULT_PRIMARY_STATE = "UT"

# Top-N list length used throughout ``/insights``.
DEFAULT_TOP_N = 10


# Fee columns in ``mart_proposal_line_items`` that carry small integer
# dollar / count values — shown in ``fee_statistics`` on /insights.
FEE_COLUMNS: tuple[str, ...] = (
    "design_fee",
    "cm_fee",
    "cm_monthly_fee",
    "contractor_ohp_fee",
    "contractor_bonds_ins",
    "contractor_co_markup",
    "city_budget",
    "contractor_days",
    "contractor_projects",
    "pm_projects",
)


# Substring fragments (lowercased) → BidTypeCategory. First match wins,
# so order matters — put narrower keywords first.
_BID_TYPE_RULES: tuple[tuple[tuple[str, ...], BidTypeCategory], ...] = (
    (("pressurized", "water", "irrigation"), BidTypeCategory.PRESSURIZED),
    (("structure", "vault"), BidTypeCategory.STRUCTURES),
    (("concrete",), BidTypeCategory.CONCRETE),
    (("earth", "grading", "excav"), BidTypeCategory.EARTHWORK),
)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


SortField = Literal["job", "owner", "bid_type", "county"]
SortDir = Literal["asc", "desc"]


def _proposal_id(job: str | None, owner: str | None, bid_type: str | None) -> str:
    """Stable 12-hex-char ID for a (job, owner, bid_type) tuple."""
    parts = [
        (job or "").strip(),
        (owner or "").strip(),
        (bid_type or "").strip(),
    ]
    digest = hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:12]


def _parse_state(county: str | None) -> str | None:
    """Extract the trailing two-letter state code from ``county``.

    ``county`` rows in the mart are formatted like ``"Utah, UT"`` or
    ``"Beaver, UT"``. We split on the last comma and accept a plain
    two-letter A–Z token.
    """
    if not county:
        return None
    _, sep, tail = county.rpartition(",")
    token = (tail if sep else county).strip().upper()
    if len(token) == 2 and token.isalpha():
        return token
    return None


def _bid_type_category(bid_type: str | None) -> BidTypeCategory:
    if not bid_type:
        return BidTypeCategory.OTHER
    needle = bid_type.lower()
    for fragments, category in _BID_TYPE_RULES:
        if any(f in needle for f in fragments):
            return category
    return BidTypeCategory.OTHER


def _geography_tier(
    state_code: str | None,
    *,
    primary_state: str = DEFAULT_PRIMARY_STATE,
) -> GeographyTier:
    if state_code is None:
        return GeographyTier.UNKNOWN
    if state_code.upper() == primary_state.upper():
        return GeographyTier.IN_STATE
    return GeographyTier.OUT_OF_STATE


# --------------------------------------------------------------------------- #
# Enrichment                                                                  #
# --------------------------------------------------------------------------- #


@dataclass
class _EnrichedProposal:
    row: dict
    id: str
    job: str
    owner: str
    bid_type: str
    county: str | None
    state_code: str | None
    bid_type_category: BidTypeCategory
    geography_tier: GeographyTier

    @property
    def list_row(self) -> ProposalListRow:
        return ProposalListRow(
            id=self.id,
            job=self.job,
            owner=self.owner,
            bid_type=self.bid_type,
            county=self.county,
            state_code=self.state_code,
            bid_type_category=self.bid_type_category,
            geography_tier=self.geography_tier,
        )


def _enrich(
    row: dict,
    *,
    primary_state: str = DEFAULT_PRIMARY_STATE,
) -> _EnrichedProposal:
    job = row.get("job") or ""
    owner = row.get("owner") or ""
    bid_type = row.get("bid_type") or ""
    county = row.get("county")
    state_code = _parse_state(county)
    return _EnrichedProposal(
        row=row,
        id=_proposal_id(job, owner, bid_type),
        job=job,
        owner=owner,
        bid_type=bid_type,
        county=county,
        state_code=state_code,
        bid_type_category=_bid_type_category(bid_type),
        geography_tier=_geography_tier(state_code, primary_state=primary_state),
    )


# --------------------------------------------------------------------------- #
# SQL fetchers                                                                #
# --------------------------------------------------------------------------- #


def _fetch_proposals(engine: Engine, tenant_id: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT job, owner, bid_type, county "
                "FROM mart_proposals WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
    return [dict(r) for r in rows]


def _fetch_line_items(engine: Engine, tenant_id: str) -> list[dict]:
    col_sql = ", ".join(["_row_hash", "competitor", *FEE_COLUMNS])
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT {col_sql} FROM mart_proposal_line_items "
                "WHERE tenant_id = :tenant_id"
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
    primary_state: str = DEFAULT_PRIMARY_STATE,
) -> ProposalsSummary:
    raws = _fetch_proposals(engine, tenant_id)
    enriched = [_enrich(r, primary_state=primary_state) for r in raws]

    total = len(enriched)
    distinct_owners = len({e.owner for e in enriched if e.owner})
    distinct_bid_types = len({e.bid_type for e in enriched if e.bid_type})
    distinct_counties = len({e.county for e in enriched if e.county})
    distinct_states = len({e.state_code for e in enriched if e.state_code})

    in_state = sum(1 for e in enriched if e.geography_tier is GeographyTier.IN_STATE)
    out_state = sum(
        1 for e in enriched if e.geography_tier is GeographyTier.OUT_OF_STATE
    )
    unk_geo = sum(
        1 for e in enriched if e.geography_tier is GeographyTier.UNKNOWN
    )

    # Line-item aggregates (tenant-wide pool).
    line_items = _fetch_line_items(engine, tenant_id)
    total_line_items = len(line_items)
    with_competitor = sum(1 for li in line_items if li.get("competitor"))
    distinct_competitors = len({
        li.get("competitor") for li in line_items if li.get("competitor")
    })

    city_budgets = [
        li["city_budget"] for li in line_items
        if li.get("city_budget") is not None
    ]
    total_city_budget = sum(city_budgets)
    avg_city_budget = (
        total_city_budget / len(city_budgets) if city_budgets else 0.0
    )

    return ProposalsSummary(
        total_proposals=total,
        distinct_owners=distinct_owners,
        distinct_bid_types=distinct_bid_types,
        distinct_counties=distinct_counties,
        distinct_states=distinct_states,
        in_state_proposals=in_state,
        out_of_state_proposals=out_state,
        unknown_geography_proposals=unk_geo,
        total_line_items=total_line_items,
        line_items_with_competitor=with_competitor,
        distinct_competitors=distinct_competitors,
        total_city_budget=int(total_city_budget),
        avg_city_budget=round(avg_city_budget, 2),
    )


def list_proposals(
    engine: Engine,
    tenant_id: str,
    *,
    page: int = 1,
    page_size: int = 25,
    sort_by: SortField = "job",
    sort_dir: SortDir = "asc",
    bid_type_category: BidTypeCategory | None = None,
    geography_tier: GeographyTier | None = None,
    bid_type: str | None = None,
    owner: str | None = None,
    county: str | None = None,
    state_code: str | None = None,
    search: str | None = None,
    primary_state: str = DEFAULT_PRIMARY_STATE,
) -> ProposalListResponse:
    """Paginated, filterable, sortable list of proposals."""
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 500:
        page_size = 25
    if sort_dir not in ("asc", "desc"):
        sort_dir = "asc"

    raws = _fetch_proposals(engine, tenant_id)
    enriched = [_enrich(r, primary_state=primary_state) for r in raws]
    rows = [e.list_row for e in enriched]

    if bid_type_category is not None:
        rows = [r for r in rows if r.bid_type_category is bid_type_category]
    if geography_tier is not None:
        rows = [r for r in rows if r.geography_tier is geography_tier]
    if bid_type is not None:
        needle = bid_type.strip()
        if needle:
            rows = [r for r in rows if r.bid_type == needle]
    if owner is not None:
        needle = owner.strip()
        if needle:
            rows = [r for r in rows if r.owner == needle]
    if county is not None:
        needle = county.strip()
        if needle:
            rows = [r for r in rows if r.county == needle]
    if state_code is not None:
        needle = state_code.strip().upper()
        if needle:
            rows = [r for r in rows if (r.state_code or "") == needle]
    if search:
        needle = search.lower()
        rows = [
            r for r in rows
            if needle in r.job.lower()
            or needle in r.owner.lower()
            or needle in r.bid_type.lower()
            or (r.county and needle in r.county.lower())
        ]

    reverse = sort_dir == "desc"

    def _key(r: ProposalListRow):
        val = getattr(r, sort_by, None)
        if isinstance(val, str):
            return val.lower()
        return val

    non_null = [r for r in rows if getattr(r, sort_by, None) is not None]
    null_rows = [r for r in rows if getattr(r, sort_by, None) is None]
    non_null.sort(key=_key, reverse=reverse)
    rows = non_null + null_rows

    total = len(rows)
    start = (page - 1) * page_size
    items = rows[start:start + page_size]

    return ProposalListResponse(
        total=total,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        items=items,
    )


def get_proposal_detail(
    engine: Engine,
    tenant_id: str,
    proposal_id: str,
    *,
    primary_state: str = DEFAULT_PRIMARY_STATE,
) -> ProposalDetail | None:
    """Fetch a single proposal by synthetic ``proposal_id``."""
    key = (proposal_id or "").strip().lower()
    if not key:
        return None

    for raw in _fetch_proposals(engine, tenant_id):
        e = _enrich(raw, primary_state=primary_state)
        if e.id == key:
            return ProposalDetail(
                id=e.id,
                job=e.job,
                owner=e.owner,
                bid_type=e.bid_type,
                county=e.county,
                state_code=e.state_code,
                bid_type_category=e.bid_type_category,
                geography_tier=e.geography_tier,
            )
    return None


def _top_n(
    values: list[str | None], *, top_n: int,
) -> list[SegmentCountRow]:
    """Count non-null strings and return the top-N as SegmentCountRows."""
    counts = Counter(v for v in values if v)
    return [
        SegmentCountRow(segment=seg, count=cnt)
        for seg, cnt in counts.most_common(top_n)
    ]


def _fee_stats(line_items: list[dict], fee: str) -> FeeStatsRow:
    values = [
        li[fee] for li in line_items
        if li.get(fee) is not None
    ]
    if not values:
        return FeeStatsRow(fee=fee, count=0, min_value=None, max_value=None, avg_value=None)
    return FeeStatsRow(
        fee=fee,
        count=len(values),
        min_value=min(values),
        max_value=max(values),
        avg_value=round(sum(values) / len(values), 2),
    )


def get_insights(
    engine: Engine,
    tenant_id: str,
    *,
    top_n: int = DEFAULT_TOP_N,
    primary_state: str = DEFAULT_PRIMARY_STATE,
) -> ProposalsInsights:
    """Precomputed analytics for the proposals dashboard."""
    raws = _fetch_proposals(engine, tenant_id)
    enriched = [_enrich(r, primary_state=primary_state) for r in raws]

    category_counts = Counter(e.bid_type_category for e in enriched)
    category_breakdown = BidTypeCategoryBreakdown(
        pressurized=category_counts.get(BidTypeCategory.PRESSURIZED, 0),
        structures=category_counts.get(BidTypeCategory.STRUCTURES, 0),
        concrete=category_counts.get(BidTypeCategory.CONCRETE, 0),
        earthwork=category_counts.get(BidTypeCategory.EARTHWORK, 0),
        other=category_counts.get(BidTypeCategory.OTHER, 0),
    )

    geo_counts = Counter(e.geography_tier for e in enriched)
    geo_breakdown = GeographyTierBreakdown(
        in_state=geo_counts.get(GeographyTier.IN_STATE, 0),
        out_of_state=geo_counts.get(GeographyTier.OUT_OF_STATE, 0),
        unknown=geo_counts.get(GeographyTier.UNKNOWN, 0),
    )

    top_owners = _top_n([e.owner for e in enriched], top_n=top_n)
    top_bid_types = _top_n([e.bid_type for e in enriched], top_n=top_n)
    top_counties = _top_n([e.county for e in enriched], top_n=top_n)
    top_states = _top_n([e.state_code for e in enriched], top_n=top_n)

    # Line-item aggregates.
    line_items = _fetch_line_items(engine, tenant_id)
    competitor_counts = Counter(
        li.get("competitor") for li in line_items if li.get("competitor")
    )
    competitor_rows = [
        CompetitorFrequencyRow(competitor=name, line_item_count=cnt)
        for name, cnt in competitor_counts.most_common(top_n)
    ]

    fee_rows = [_fee_stats(line_items, fee) for fee in FEE_COLUMNS]

    return ProposalsInsights(
        bid_type_category_breakdown=category_breakdown,
        geography_tier_breakdown=geo_breakdown,
        top_owners=top_owners,
        top_bid_types=top_bid_types,
        top_counties=top_counties,
        top_states=top_states,
        competitor_frequency=competitor_rows,
        fee_statistics=fee_rows,
    )
