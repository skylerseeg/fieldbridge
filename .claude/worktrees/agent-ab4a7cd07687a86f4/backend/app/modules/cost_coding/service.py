"""Cost-coding service — pure query functions against the SQLite marts.

Reads a single mart:
  - ``mart_hcss_activities`` (~104k rows, ~3.8k distinct activity codes).

Each row is one (estimate, activity_code) line item with five cost
buckets: labor / permanent material / construction material / equipment
/ subcontract. This module aggregates *by activity code* across every
estimate it appears in.

Classification model:
  1. **CostCategory** — which bucket dominates (default >= 60% share).
     MIXED if no dominant bucket, ZERO if total direct cost == 0.
  2. **CostSizeTier** — dollar magnitude. Thresholds tunable per request.
  3. **UsageTier** — distinct-estimate count. Thresholds tunable.

Helpers (``_major_code``, ``_cost_category``, ``_size_tier``,
``_usage_tier``) are pure and unit-testable.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import Engine, text

from app.modules.cost_coding.schema import (
    CostCategory,
    CostCategoryBreakdown,
    CostCategoryMixRow,
    CostCodeDetail,
    CostCodeEstimateBreakdown,
    CostCodeListResponse,
    CostCodeListRow,
    CostCodingInsights,
    CostCodingSummary,
    CostSizeTier,
    MajorCodeRollup,
    SizeTierBreakdown,
    TopCostCodeRow,
    UsageTier,
    UsageTierBreakdown,
)


# --------------------------------------------------------------------------- #
# Tunables                                                                    #
# --------------------------------------------------------------------------- #


# Share threshold a single bucket must cross to "dominate" a code's
# cost category. 0.6 = 60% — matches typical construction estimating
# conventions where a code is clearly labor- or material-driven.
DEFAULT_CATEGORY_DOMINANCE_THRESHOLD = 0.6

# Dollar thresholds for CostSizeTier. Real marts carry six- and
# seven-figure totals per code; these defaults work for production.
# Tests override with tighter thresholds that fit seeded fixtures.
DEFAULT_MAJOR_COST_MIN = 100_000.0
DEFAULT_SIGNIFICANT_COST_MIN = 10_000.0

# Usage thresholds (distinct estimates per code).
DEFAULT_HEAVY_MIN_ESTIMATES = 50
DEFAULT_REGULAR_MIN_ESTIMATES = 10

# How many rows to return per top-N insight list.
DEFAULT_TOP_N = 10

# How many estimates to include in a ``CostCodeDetail.estimates`` list.
DEFAULT_DETAIL_ESTIMATES = 20


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


SortField = Literal[
    "code",
    "estimate_count",
    "total_direct_cost",
    "total_man_hours",
    "labor_cost",
    "equipment_cost",
    "subcontract_cost",
]
SortDir = Literal["asc", "desc"]


def _norm_code(s: str | None) -> str | None:
    """Canonical code form — stripped. Empty → None."""
    if s is None:
        return None
    out = s.strip()
    return out or None


def _major_code(code: str | None) -> str | None:
    """Pre-dot prefix of an activity code.

    ``"1101.100"`` → ``"1101"``.
    ``"900.9010"`` → ``"900"``.
    ``"02300"``    → ``"02300"`` (no dot → full code).
    ``".1"``       → None (empty prefix).
    """
    if not code:
        return None
    head = code.split(".", 1)[0].strip()
    return head or None


def _cost_category(
    labor: float,
    perm_mat: float,
    const_mat: float,
    equipment: float,
    subcontract: float,
    *,
    dominance: float = DEFAULT_CATEGORY_DOMINANCE_THRESHOLD,
) -> CostCategory:
    """Pick the dominant bucket, else MIXED (or ZERO for $0 totals)."""
    total = labor + perm_mat + const_mat + equipment + subcontract
    if total <= 0:
        return CostCategory.ZERO
    buckets = (
        (CostCategory.LABOR, labor),
        (CostCategory.PERMANENT_MATERIAL, perm_mat),
        (CostCategory.CONSTRUCTION_MATERIAL, const_mat),
        (CostCategory.EQUIPMENT, equipment),
        (CostCategory.SUBCONTRACT, subcontract),
    )
    for cat, amount in buckets:
        if amount / total >= dominance:
            return cat
    return CostCategory.MIXED


def _size_tier(
    total_cost: float,
    *,
    major_min: float = DEFAULT_MAJOR_COST_MIN,
    significant_min: float = DEFAULT_SIGNIFICANT_COST_MIN,
) -> CostSizeTier:
    if total_cost <= 0:
        return CostSizeTier.ZERO
    if total_cost >= major_min:
        return CostSizeTier.MAJOR
    if total_cost >= significant_min:
        return CostSizeTier.SIGNIFICANT
    return CostSizeTier.MINOR


def _usage_tier(
    estimate_count: int,
    *,
    heavy_min: int = DEFAULT_HEAVY_MIN_ESTIMATES,
    regular_min: int = DEFAULT_REGULAR_MIN_ESTIMATES,
) -> UsageTier:
    if estimate_count >= heavy_min:
        return UsageTier.HEAVY
    if estimate_count >= regular_min:
        return UsageTier.REGULAR
    if estimate_count >= 2:
        return UsageTier.LIGHT
    return UsageTier.SINGLETON


# --------------------------------------------------------------------------- #
# Rollup                                                                      #
# --------------------------------------------------------------------------- #


@dataclass
class _CodeRollup:
    """Accumulator for one activity code across all its estimate rows."""

    code: str
    estimates: set[str] = field(default_factory=set)
    descriptions: Counter = field(default_factory=Counter)
    estimate_names: dict[str, str] = field(default_factory=dict)
    per_estimate: dict[str, dict] = field(default_factory=dict)

    total_man_hours: float = 0.0
    total_direct_cost: float = 0.0
    labor_cost: float = 0.0
    permanent_material_cost: float = 0.0
    construction_material_cost: float = 0.0
    equipment_cost: float = 0.0
    subcontract_cost: float = 0.0

    def ingest(self, row: dict) -> None:
        est = row.get("estimate_code") or ""
        self.estimates.add(est)
        desc = row.get("activity_description")
        if desc:
            self.descriptions[desc] += 1
        est_name = row.get("estimate_name")
        if est and est_name and est not in self.estimate_names:
            self.estimate_names[est] = est_name

        man = row.get("man_hours") or 0.0
        direct = row.get("direct_total_cost") or 0.0
        labor = row.get("labor_cost") or 0.0
        perm_mat = row.get("permanent_material_cost") or 0.0
        const_mat = row.get("construction_material_cost") or 0.0
        equip = row.get("equipment_cost") or 0.0
        sub = row.get("subcontract_cost") or 0.0

        self.total_man_hours += man
        self.total_direct_cost += direct
        self.labor_cost += labor
        self.permanent_material_cost += perm_mat
        self.construction_material_cost += const_mat
        self.equipment_cost += equip
        self.subcontract_cost += sub

        # Per-estimate aggregates — mart can have multiple rows per
        # (estimate, code) if a tenant re-ingested. Accumulate.
        slot = self.per_estimate.setdefault(
            est,
            {
                "estimate_code": est,
                "estimate_name": est_name,
                "activity_description": desc,
                "man_hours": 0.0,
                "direct_total_cost": 0.0,
                "labor_cost": 0.0,
                "permanent_material_cost": 0.0,
                "construction_material_cost": 0.0,
                "equipment_cost": 0.0,
                "subcontract_cost": 0.0,
            },
        )
        slot["man_hours"] += man
        slot["direct_total_cost"] += direct
        slot["labor_cost"] += labor
        slot["permanent_material_cost"] += perm_mat
        slot["construction_material_cost"] += const_mat
        slot["equipment_cost"] += equip
        slot["subcontract_cost"] += sub
        if est_name and not slot.get("estimate_name"):
            slot["estimate_name"] = est_name
        if desc and not slot.get("activity_description"):
            slot["activity_description"] = desc

    def canonical_description(self) -> str | None:
        if not self.descriptions:
            return None
        # Counter.most_common breaks ties by insertion order; normalize
        # to alphabetical to make the rollup deterministic across runs.
        top = self.descriptions.most_common()
        top_count = top[0][1]
        tied = [d for d, c in top if c == top_count]
        tied.sort()
        return tied[0]

    def list_row(
        self,
        *,
        category_dominance: float,
        major_cost_min: float,
        significant_cost_min: float,
        heavy_min: int,
        regular_min: int,
    ) -> CostCodeListRow:
        category = _cost_category(
            self.labor_cost,
            self.permanent_material_cost,
            self.construction_material_cost,
            self.equipment_cost,
            self.subcontract_cost,
            dominance=category_dominance,
        )
        size = _size_tier(
            self.total_direct_cost,
            major_min=major_cost_min,
            significant_min=significant_cost_min,
        )
        usage = _usage_tier(
            len(self.estimates),
            heavy_min=heavy_min,
            regular_min=regular_min,
        )
        return CostCodeListRow(
            id=self.code,
            code=self.code,
            description=self.canonical_description(),
            major_code=_major_code(self.code),
            estimate_count=len(self.estimates),
            total_man_hours=round(self.total_man_hours, 2),
            total_direct_cost=round(self.total_direct_cost, 2),
            labor_cost=round(self.labor_cost, 2),
            permanent_material_cost=round(self.permanent_material_cost, 2),
            construction_material_cost=round(
                self.construction_material_cost, 2
            ),
            equipment_cost=round(self.equipment_cost, 2),
            subcontract_cost=round(self.subcontract_cost, 2),
            cost_category=category,
            size_tier=size,
            usage_tier=usage,
        )


# --------------------------------------------------------------------------- #
# SQL fetcher                                                                 #
# --------------------------------------------------------------------------- #


def _fetch_all(engine: Engine, tenant_id: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT estimate_code, activity_code, estimate_name,
                       activity_description, man_hours, direct_total_cost,
                       labor_cost, permanent_material_cost,
                       construction_material_cost, equipment_cost,
                       subcontract_cost
                FROM mart_hcss_activities
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
    return [dict(r) for r in rows]


def _rollup(engine: Engine, tenant_id: str) -> dict[str, _CodeRollup]:
    rollups: dict[str, _CodeRollup] = {}
    for raw in _fetch_all(engine, tenant_id):
        code = _norm_code(raw.get("activity_code"))
        if not code:
            continue
        slot = rollups.get(code)
        if slot is None:
            slot = _CodeRollup(code=code)
            rollups[code] = slot
        slot.ingest(raw)
    return rollups


# --------------------------------------------------------------------------- #
# Public query API                                                            #
# --------------------------------------------------------------------------- #


def get_summary(engine: Engine, tenant_id: str) -> CostCodingSummary:
    rollups = _rollup(engine, tenant_id)

    # total_activities = raw mart row count (one per (estimate, code)
    # pair per ingest). Single scalar query is cheaper than rescanning.
    with engine.connect() as conn:
        total_activities = conn.execute(
            text(
                "SELECT COUNT(*) FROM mart_hcss_activities "
                "WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        ).scalar_one()

    distinct_estimates: set[str] = set()
    for r in rollups.values():
        distinct_estimates.update(r.estimates)

    total_man_hours = sum(r.total_man_hours for r in rollups.values())
    total_direct_cost = sum(r.total_direct_cost for r in rollups.values())
    total_labor = sum(r.labor_cost for r in rollups.values())
    total_perm_mat = sum(r.permanent_material_cost for r in rollups.values())
    total_const_mat = sum(
        r.construction_material_cost for r in rollups.values()
    )
    total_equip = sum(r.equipment_cost for r in rollups.values())
    total_sub = sum(r.subcontract_cost for r in rollups.values())

    with_labor = sum(1 for r in rollups.values() if r.labor_cost > 0)
    with_perm = sum(
        1 for r in rollups.values() if r.permanent_material_cost > 0
    )
    with_const = sum(
        1 for r in rollups.values() if r.construction_material_cost > 0
    )
    with_equip = sum(1 for r in rollups.values() if r.equipment_cost > 0)
    with_sub = sum(1 for r in rollups.values() if r.subcontract_cost > 0)
    uncosted = sum(
        1 for r in rollups.values() if r.total_direct_cost <= 0
    )

    return CostCodingSummary(
        total_codes=len(rollups),
        total_activities=int(total_activities),
        distinct_estimates=len(distinct_estimates),
        total_man_hours=round(total_man_hours, 2),
        total_direct_cost=round(total_direct_cost, 2),
        total_labor_cost=round(total_labor, 2),
        total_permanent_material_cost=round(total_perm_mat, 2),
        total_construction_material_cost=round(total_const_mat, 2),
        total_equipment_cost=round(total_equip, 2),
        total_subcontract_cost=round(total_sub, 2),
        codes_with_labor=with_labor,
        codes_with_permanent_material=with_perm,
        codes_with_construction_material=with_const,
        codes_with_equipment=with_equip,
        codes_with_subcontract=with_sub,
        uncosted_codes=uncosted,
    )


def list_cost_codes(
    engine: Engine,
    tenant_id: str,
    *,
    page: int = 1,
    page_size: int = 25,
    sort_by: SortField = "total_direct_cost",
    sort_dir: SortDir = "desc",
    cost_category: CostCategory | None = None,
    size_tier: CostSizeTier | None = None,
    usage_tier: UsageTier | None = None,
    major_code: str | None = None,
    search: str | None = None,
    category_dominance: float = DEFAULT_CATEGORY_DOMINANCE_THRESHOLD,
    major_cost_min: float = DEFAULT_MAJOR_COST_MIN,
    significant_cost_min: float = DEFAULT_SIGNIFICANT_COST_MIN,
    heavy_min: int = DEFAULT_HEAVY_MIN_ESTIMATES,
    regular_min: int = DEFAULT_REGULAR_MIN_ESTIMATES,
) -> CostCodeListResponse:
    """Paginated, filterable, sortable list of cost codes."""
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 500:
        page_size = 25
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"

    rollups = _rollup(engine, tenant_id)
    rows = [
        r.list_row(
            category_dominance=category_dominance,
            major_cost_min=major_cost_min,
            significant_cost_min=significant_cost_min,
            heavy_min=heavy_min,
            regular_min=regular_min,
        )
        for r in rollups.values()
    ]

    if cost_category is not None:
        rows = [r for r in rows if r.cost_category is cost_category]
    if size_tier is not None:
        rows = [r for r in rows if r.size_tier is size_tier]
    if usage_tier is not None:
        rows = [r for r in rows if r.usage_tier is usage_tier]
    if major_code is not None:
        needle = major_code.strip()
        if needle:
            rows = [r for r in rows if r.major_code == needle]
    if search:
        needle = search.lower()
        rows = [
            r for r in rows
            if needle in r.code.lower()
            or (r.description and needle in r.description.lower())
        ]

    reverse = sort_dir == "desc"

    def _key(r: CostCodeListRow):
        val = getattr(r, sort_by, None)
        if sort_by == "code" and isinstance(val, str):
            return val.lower()
        return val

    non_null = [r for r in rows if getattr(r, sort_by, None) is not None]
    null_rows = [r for r in rows if getattr(r, sort_by, None) is None]
    non_null.sort(key=_key, reverse=reverse)
    rows = non_null + null_rows

    total = len(rows)
    start = (page - 1) * page_size
    items = rows[start:start + page_size]

    return CostCodeListResponse(
        total=total,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        items=items,
    )


def get_cost_code_detail(
    engine: Engine,
    tenant_id: str,
    code_id: str,
    *,
    detail_estimates: int = DEFAULT_DETAIL_ESTIMATES,
    category_dominance: float = DEFAULT_CATEGORY_DOMINANCE_THRESHOLD,
    major_cost_min: float = DEFAULT_MAJOR_COST_MIN,
    significant_cost_min: float = DEFAULT_SIGNIFICANT_COST_MIN,
    heavy_min: int = DEFAULT_HEAVY_MIN_ESTIMATES,
    regular_min: int = DEFAULT_REGULAR_MIN_ESTIMATES,
) -> CostCodeDetail | None:
    """Single cost-code detail with top-N per-estimate breakdown."""
    key = _norm_code(code_id)
    if not key:
        return None

    rollups = _rollup(engine, tenant_id)
    r = rollups.get(key)
    if r is None:
        return None

    lr = r.list_row(
        category_dominance=category_dominance,
        major_cost_min=major_cost_min,
        significant_cost_min=significant_cost_min,
        heavy_min=heavy_min,
        regular_min=regular_min,
    )

    per_est_rows = list(r.per_estimate.values())
    per_est_rows.sort(
        key=lambda row: row.get("direct_total_cost", 0.0),
        reverse=True,
    )
    capped = per_est_rows[:detail_estimates]
    breakdown = [
        CostCodeEstimateBreakdown(
            estimate_code=row["estimate_code"],
            estimate_name=row.get("estimate_name"),
            activity_description=row.get("activity_description"),
            man_hours=round(row.get("man_hours") or 0.0, 2),
            direct_total_cost=round(row.get("direct_total_cost") or 0.0, 2),
            labor_cost=round(row.get("labor_cost") or 0.0, 2),
            permanent_material_cost=round(
                row.get("permanent_material_cost") or 0.0, 2
            ),
            construction_material_cost=round(
                row.get("construction_material_cost") or 0.0, 2
            ),
            equipment_cost=round(row.get("equipment_cost") or 0.0, 2),
            subcontract_cost=round(row.get("subcontract_cost") or 0.0, 2),
        )
        for row in capped
    ]

    return CostCodeDetail(
        id=lr.id,
        code=lr.code,
        description=lr.description,
        major_code=lr.major_code,
        estimate_count=lr.estimate_count,
        total_man_hours=lr.total_man_hours,
        total_direct_cost=lr.total_direct_cost,
        labor_cost=lr.labor_cost,
        permanent_material_cost=lr.permanent_material_cost,
        construction_material_cost=lr.construction_material_cost,
        equipment_cost=lr.equipment_cost,
        subcontract_cost=lr.subcontract_cost,
        cost_category=lr.cost_category,
        size_tier=lr.size_tier,
        usage_tier=lr.usage_tier,
        distinct_descriptions=len(r.descriptions),
        estimates=breakdown,
    )


def get_insights(
    engine: Engine,
    tenant_id: str,
    *,
    top_n: int = DEFAULT_TOP_N,
    category_dominance: float = DEFAULT_CATEGORY_DOMINANCE_THRESHOLD,
    major_cost_min: float = DEFAULT_MAJOR_COST_MIN,
    significant_cost_min: float = DEFAULT_SIGNIFICANT_COST_MIN,
    heavy_min: int = DEFAULT_HEAVY_MIN_ESTIMATES,
    regular_min: int = DEFAULT_REGULAR_MIN_ESTIMATES,
) -> CostCodingInsights:
    """Precomputed analytics for the cost-coding dashboard."""
    rollups = _rollup(engine, tenant_id)
    rows = [
        r.list_row(
            category_dominance=category_dominance,
            major_cost_min=major_cost_min,
            significant_cost_min=significant_cost_min,
            heavy_min=heavy_min,
            regular_min=regular_min,
        )
        for r in rollups.values()
    ]

    # Category breakdown — count codes in each dominant bucket.
    cat_counts = Counter(r.cost_category for r in rows)
    category_breakdown = CostCategoryBreakdown(
        labor=cat_counts.get(CostCategory.LABOR, 0),
        permanent_material=cat_counts.get(CostCategory.PERMANENT_MATERIAL, 0),
        construction_material=cat_counts.get(
            CostCategory.CONSTRUCTION_MATERIAL, 0
        ),
        equipment=cat_counts.get(CostCategory.EQUIPMENT, 0),
        subcontract=cat_counts.get(CostCategory.SUBCONTRACT, 0),
        mixed=cat_counts.get(CostCategory.MIXED, 0),
        zero=cat_counts.get(CostCategory.ZERO, 0),
    )

    size_counts = Counter(r.size_tier for r in rows)
    size_breakdown = SizeTierBreakdown(
        major=size_counts.get(CostSizeTier.MAJOR, 0),
        significant=size_counts.get(CostSizeTier.SIGNIFICANT, 0),
        minor=size_counts.get(CostSizeTier.MINOR, 0),
        zero=size_counts.get(CostSizeTier.ZERO, 0),
    )

    usage_counts = Counter(r.usage_tier for r in rows)
    usage_breakdown = UsageTierBreakdown(
        heavy=usage_counts.get(UsageTier.HEAVY, 0),
        regular=usage_counts.get(UsageTier.REGULAR, 0),
        light=usage_counts.get(UsageTier.LIGHT, 0),
        singleton=usage_counts.get(UsageTier.SINGLETON, 0),
    )

    # Per-category share of total direct cost across the portfolio.
    # Counted by *bucket* not by dominant-category — a MIXED code's
    # labor dollars still count against labor share.
    bucket_totals = {
        CostCategory.LABOR: sum(r.labor_cost for r in rows),
        CostCategory.PERMANENT_MATERIAL: sum(
            r.permanent_material_cost for r in rows
        ),
        CostCategory.CONSTRUCTION_MATERIAL: sum(
            r.construction_material_cost for r in rows
        ),
        CostCategory.EQUIPMENT: sum(r.equipment_cost for r in rows),
        CostCategory.SUBCONTRACT: sum(r.subcontract_cost for r in rows),
    }
    total_direct = sum(bucket_totals.values())
    category_mix = [
        CostCategoryMixRow(
            category=cat,
            code_count=cat_counts.get(cat, 0),
            total_direct_cost=round(amount, 2),
            share_of_total=(
                round(amount / total_direct, 4) if total_direct > 0 else 0.0
            ),
        )
        for cat, amount in bucket_totals.items()
    ]

    def _top_row(r: CostCodeListRow) -> TopCostCodeRow:
        return TopCostCodeRow(
            code=r.code,
            description=r.description,
            estimate_count=r.estimate_count,
            total_direct_cost=r.total_direct_cost,
            total_man_hours=r.total_man_hours,
            cost_category=r.cost_category,
        )

    top_by_cost = [
        _top_row(r)
        for r in sorted(
            rows, key=lambda r: r.total_direct_cost, reverse=True,
        )[:top_n]
    ]
    top_by_usage = [
        _top_row(r)
        for r in sorted(
            rows, key=lambda r: r.estimate_count, reverse=True,
        )[:top_n]
    ]
    top_by_hours = [
        _top_row(r)
        for r in sorted(
            rows, key=lambda r: r.total_man_hours, reverse=True,
        )[:top_n]
    ]

    # Major-code prefix rollup — aggregate codes sharing a pre-dot prefix.
    major_rollups: dict[str, dict] = defaultdict(
        lambda: {
            "code_count": 0,
            "estimates": set(),
            "total_direct_cost": 0.0,
            "total_man_hours": 0.0,
            "example_description": None,
        }
    )
    for r in rollups.values():
        m = _major_code(r.code)
        if m is None:
            continue
        slot = major_rollups[m]
        slot["code_count"] += 1
        slot["estimates"].update(r.estimates)
        slot["total_direct_cost"] += r.total_direct_cost
        slot["total_man_hours"] += r.total_man_hours
        if slot["example_description"] is None:
            slot["example_description"] = r.canonical_description()

    top_major_codes = [
        MajorCodeRollup(
            major_code=m,
            code_count=slot["code_count"],
            estimate_count=len(slot["estimates"]),
            total_direct_cost=round(slot["total_direct_cost"], 2),
            total_man_hours=round(slot["total_man_hours"], 2),
            example_description=slot["example_description"],
        )
        for m, slot in sorted(
            major_rollups.items(),
            key=lambda kv: kv[1]["total_direct_cost"],
            reverse=True,
        )[:top_n]
    ]

    uncosted = [
        _top_row(r) for r in rows if r.total_direct_cost <= 0
    ]
    uncosted.sort(key=lambda r: r.code.lower())
    uncosted_capped = uncosted[:top_n]

    return CostCodingInsights(
        category_breakdown=category_breakdown,
        size_tier_breakdown=size_breakdown,
        usage_tier_breakdown=usage_breakdown,
        category_mix=category_mix,
        top_by_cost=top_by_cost,
        top_by_usage=top_by_usage,
        top_by_hours=top_by_hours,
        top_major_codes=top_major_codes,
        uncosted_codes=uncosted_capped,
    )
