"""Fleet P&L service — pure query functions against the SQLite marts.

Reads from two marts:
  - mart_equipment_utilization  (~8k haul tickets across ~20 trucks)
  - mart_equipment_rentals      (rental-in contracts)

Primary entity is the truck, rolled up from utilization tickets.
Rental-in data is surfaced only at the fleet aggregate level — the
rentals mart is keyed by equipment description + vendor, not by
VanCon truck tag, so per-truck attribution isn't possible without
a join table that doesn't exist yet.

Ticket-level fields used:
  truck, ticket_date, ticket, job, vendor, pit, material, driver,
  qty, price, extended_price, invoiced, is_lessor.

Job strings share Vista's leading-space quirk (``' 2516. Ephraim...'``);
``_strip_job_key`` normalizes them when computing the job mix.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import Engine, text

from app.modules.fleet_pnl.schema import (
    FleetMixRow,
    FleetMonthlyPoint,
    FleetPnlInsights,
    FleetSummary,
    FleetTicketPoint,
    FleetTruckDetail,
    InvoiceBreakdown,
    InvoiceBucket,
    LessorFlag,
    RentalInSummary,
    TruckListResponse,
    TruckListRow,
    TruckMoneyRow,
    UtilizationBreakdown,
    UtilizationBucket,
)


# --------------------------------------------------------------------------- #
# Tunables                                                                    #
# --------------------------------------------------------------------------- #

# Ticket-count boundary between underutilized and healthy. Tuned for the
# VanCon reference dataset (~20 trucks / ~8k tickets over the active
# window) — a truck below this count deserves attention.
DEFAULT_UNDERUTILIZED_MAX_TICKETS = 20

# Ticket-count boundary into "heavily_utilized". Trucks above this are
# the fleet's workhorses — watch-list for maintenance and driver rotation.
DEFAULT_HEAVILY_UTILIZED_MIN_TICKETS = 200

# How many rows to return per top-N insight list.
DEFAULT_TOP_N = 10

# How many most-recent tickets to inline on a detail response.
DEFAULT_RECENT_TICKETS = 20

# How many mix rows to return per detail breakdown.
DEFAULT_MIX_LIMIT = 5


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


SortField = Literal[
    "truck", "ticket_count", "revenue", "uninvoiced_revenue",
    "invoiced_revenue", "total_qty", "invoice_rate",
    "jobs_served", "vendors_served", "last_ticket",
]
SortDir = Literal["asc", "desc"]


def _strip_job_key(s: str | None) -> str | None:
    """Collapse whitespace on job strings. None/empty stays None."""
    if s is None:
        return None
    out = " ".join(s.split())
    return out or None


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


def _bool(v) -> bool | None:
    """SQLite stores booleans as 0/1; None stays None."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    return bool(v)


def _utilization_bucket(
    ticket_count: int,
    underutilized_max: int,
    heavily_min: int,
) -> UtilizationBucket:
    if ticket_count <= 0:
        return UtilizationBucket.IDLE
    if ticket_count <= underutilized_max:
        return UtilizationBucket.UNDERUTILIZED
    if ticket_count >= heavily_min:
        return UtilizationBucket.HEAVILY_UTILIZED
    return UtilizationBucket.HEALTHY


def _invoice_bucket(
    invoiced_count: int, ticket_count: int, has_invoiced_data: bool,
) -> InvoiceBucket:
    if ticket_count == 0:
        return InvoiceBucket.UNKNOWN
    if not has_invoiced_data:
        return InvoiceBucket.UNKNOWN
    if invoiced_count == 0:
        return InvoiceBucket.UNINVOICED
    if invoiced_count == ticket_count:
        return InvoiceBucket.FULLY_INVOICED
    return InvoiceBucket.PARTIALLY_INVOICED


def _lessor_flag(owned_count: int, lessor_count: int) -> LessorFlag:
    if owned_count == 0 and lessor_count == 0:
        return LessorFlag.UNKNOWN
    if owned_count > 0 and lessor_count > 0:
        return LessorFlag.MIXED
    if lessor_count > 0:
        return LessorFlag.LESSOR
    return LessorFlag.OWNED


# --------------------------------------------------------------------------- #
# Per-truck rollup                                                            #
# --------------------------------------------------------------------------- #


@dataclass
class _TruckRollup:
    truck: str
    tickets: list[dict] = field(default_factory=list)

    # Accumulators — populated by ``finalize``.
    ticket_count: int = 0
    total_qty: float = 0.0
    revenue: float = 0.0
    invoiced_count: int = 0
    invoiced_revenue: float = 0.0
    uninvoiced_revenue: float = 0.0
    has_invoiced_data: bool = False
    owned_count: int = 0
    lessor_count: int = 0
    job_keys: set[str] = field(default_factory=set)
    vendor_keys: set[str] = field(default_factory=set)
    driver_keys: set[str] = field(default_factory=set)
    first_ticket: datetime | None = None
    last_ticket: datetime | None = None
    top_material: str | None = None
    top_vendor: str | None = None
    top_job: str | None = None
    top_driver: str | None = None

    # Mix counters — kept for detail endpoint reuse.
    vendor_counter: Counter = field(default_factory=Counter)
    material_counter: Counter = field(default_factory=Counter)
    job_counter: Counter = field(default_factory=Counter)
    driver_counter: Counter = field(default_factory=Counter)
    vendor_revenue: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    material_revenue: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    job_revenue: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    driver_revenue: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    vendor_qty: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    material_qty: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    job_qty: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    driver_qty: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    def finalize(self) -> None:
        for t in self.tickets:
            self.ticket_count += 1
            qty = _f(t.get("qty")) or 0.0
            price = _f(t.get("extended_price")) or 0.0
            self.total_qty += qty
            self.revenue += price

            invoiced = _bool(t.get("invoiced"))
            if t.get("invoiced") is not None:
                self.has_invoiced_data = True
            if invoiced:
                self.invoiced_count += 1
                self.invoiced_revenue += price
            elif invoiced is False:
                self.uninvoiced_revenue += price

            lessor = _bool(t.get("is_lessor"))
            if lessor is True:
                self.lessor_count += 1
            elif lessor is False:
                self.owned_count += 1

            job = _strip_job_key(t.get("job"))
            if job:
                self.job_keys.add(job)
                self.job_counter[job] += 1
                self.job_revenue[job] += price
                self.job_qty[job] += qty

            vendor = (t.get("vendor") or "").strip() or None
            if vendor:
                self.vendor_keys.add(vendor)
                self.vendor_counter[vendor] += 1
                self.vendor_revenue[vendor] += price
                self.vendor_qty[vendor] += qty

            material = (t.get("material") or "").strip() or None
            if material:
                self.material_counter[material] += 1
                self.material_revenue[material] += price
                self.material_qty[material] += qty

            driver = (t.get("driver") or "").strip() or None
            if driver:
                self.driver_keys.add(driver)
                self.driver_counter[driver] += 1
                self.driver_revenue[driver] += price
                self.driver_qty[driver] += qty

            dt = _normalize_dt(t.get("ticket_date"))
            if dt is not None:
                if self.first_ticket is None or dt < self.first_ticket:
                    self.first_ticket = dt
                if self.last_ticket is None or dt > self.last_ticket:
                    self.last_ticket = dt

        if self.vendor_counter:
            self.top_vendor = self.vendor_counter.most_common(1)[0][0]
        if self.material_counter:
            self.top_material = self.material_counter.most_common(1)[0][0]
        if self.job_counter:
            self.top_job = self.job_counter.most_common(1)[0][0]
        if self.driver_counter:
            self.top_driver = self.driver_counter.most_common(1)[0][0]

    @property
    def avg_price_per_ticket(self) -> float | None:
        return (self.revenue / self.ticket_count) if self.ticket_count else None

    @property
    def invoice_rate(self) -> float | None:
        if not self.ticket_count:
            return None
        return self.invoiced_count / self.ticket_count

    @property
    def active_days(self) -> int | None:
        if self.first_ticket is None or self.last_ticket is None:
            return None
        return (self.last_ticket - self.first_ticket).days + 1


def _rollup(
    util_rows: list[dict],
    *,
    underutilized_max: int,
    heavily_min: int,
) -> list[_TruckRollup]:
    by_truck: dict[str, _TruckRollup] = {}
    for r in util_rows:
        truck = (r.get("truck") or "").strip()
        if not truck:
            continue
        bucket = by_truck.setdefault(truck, _TruckRollup(truck=truck))
        bucket.tickets.append(r)
    for b in by_truck.values():
        b.finalize()
    return list(by_truck.values())


def _to_list_row(
    r: _TruckRollup,
    *,
    underutilized_max: int,
    heavily_min: int,
) -> TruckListRow:
    return TruckListRow(
        id=r.truck,
        truck=r.truck,
        ticket_count=r.ticket_count,
        total_qty=r.total_qty,
        revenue=r.revenue,
        avg_price_per_ticket=r.avg_price_per_ticket,
        invoiced_count=r.invoiced_count,
        invoiced_revenue=r.invoiced_revenue,
        uninvoiced_revenue=r.uninvoiced_revenue,
        invoice_rate=r.invoice_rate,
        jobs_served=len(r.job_keys),
        vendors_served=len(r.vendor_keys),
        first_ticket=r.first_ticket,
        last_ticket=r.last_ticket,
        active_days=r.active_days,
        lessor_flag=_lessor_flag(r.owned_count, r.lessor_count),
        invoice_bucket=_invoice_bucket(
            r.invoiced_count, r.ticket_count, r.has_invoiced_data,
        ),
        utilization_bucket=_utilization_bucket(
            r.ticket_count, underutilized_max, heavily_min,
        ),
        top_material=r.top_material,
        top_vendor=r.top_vendor,
        top_job=r.top_job,
        top_driver=r.top_driver,
    )


# --------------------------------------------------------------------------- #
# SQL fetchers                                                                #
# --------------------------------------------------------------------------- #


def _fetch_utilization(engine: Engine, tenant_id: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT ticket_date, ticket, truck, job, is_lessor,
                       invoiced, invoice_number, invoice_date,
                       price, extended_price, vendor, pit, material,
                       qty, units, driver
                FROM mart_equipment_utilization
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
    return [dict(r) for r in rows]


def _fetch_rentals(engine: Engine, tenant_id: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT equipment, rental_company, picked_up_date,
                       scheduled_return_date, returned_date, rate,
                       rate_unit, is_rpo
                FROM mart_equipment_rentals
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Rental-in aggregation                                                       #
# --------------------------------------------------------------------------- #


def _rental_summary(rows: list[dict], *, top_n: int = DEFAULT_TOP_N) -> RentalInSummary:
    total_monthly = 0.0
    total_hourly = 0.0
    active = 0
    rpo = 0
    vendor_counter: Counter = Counter()
    vendor_monthly: dict[str, float] = defaultdict(float)

    for r in rows:
        rate = _f(r.get("rate")) or 0.0
        unit = (r.get("rate_unit") or "").strip().lower()
        if unit == "monthly":
            total_monthly += rate
        elif unit == "hourly":
            total_hourly += rate

        if r.get("returned_date") in (None, ""):
            active += 1
        if _bool(r.get("is_rpo")):
            rpo += 1

        vendor = (r.get("rental_company") or "").strip() or None
        if vendor:
            vendor_counter[vendor] += 1
            if unit == "monthly":
                vendor_monthly[vendor] += rate

    top_vendors = [
        FleetMixRow(
            label=v,
            ticket_count=count,
            revenue=vendor_monthly.get(v, 0.0),
            qty=0.0,
        )
        for v, count in vendor_counter.most_common(top_n)
    ]

    return RentalInSummary(
        contracts=len(rows),
        active_contracts=active,
        rpo_contracts=rpo,
        total_monthly_cost=total_monthly,
        total_hourly_cost=total_hourly,
        top_rental_vendors=top_vendors,
    )


# --------------------------------------------------------------------------- #
# Public query API                                                            #
# --------------------------------------------------------------------------- #


def get_summary(
    engine: Engine,
    tenant_id: str,
    *,
    underutilized_max_tickets: int = DEFAULT_UNDERUTILIZED_MAX_TICKETS,
    heavily_utilized_min_tickets: int = DEFAULT_HEAVILY_UTILIZED_MIN_TICKETS,
) -> FleetSummary:
    util = _fetch_utilization(engine, tenant_id)
    rentals = _fetch_rentals(engine, tenant_id)

    rollups = _rollup(
        util,
        underutilized_max=underutilized_max_tickets,
        heavily_min=heavily_utilized_min_tickets,
    )

    total_trucks = len(rollups)
    total_tickets = sum(r.ticket_count for r in rollups)
    total_qty = sum(r.total_qty for r in rollups)
    total_revenue = sum(r.revenue for r in rollups)
    invoiced_rev = sum(r.invoiced_revenue for r in rollups)
    uninvoiced_rev = sum(r.uninvoiced_revenue for r in rollups)
    invoiced_count = sum(r.invoiced_count for r in rollups)

    invoice_rate: float | None
    invoice_rate = invoiced_count / total_tickets if total_tickets else None

    owned = sum(
        1 for r in rollups
        if _lessor_flag(r.owned_count, r.lessor_count) is LessorFlag.OWNED
    )
    lessor = sum(
        1 for r in rollups
        if _lessor_flag(r.owned_count, r.lessor_count) is LessorFlag.LESSOR
    )
    mixed = sum(
        1 for r in rollups
        if _lessor_flag(r.owned_count, r.lessor_count) is LessorFlag.MIXED
    )
    unknown = sum(
        1 for r in rollups
        if _lessor_flag(r.owned_count, r.lessor_count) is LessorFlag.UNKNOWN
    )

    first_ticket = min(
        (r.first_ticket for r in rollups if r.first_ticket is not None),
        default=None,
    )
    last_ticket = max(
        (r.last_ticket for r in rollups if r.last_ticket is not None),
        default=None,
    )
    active_days: int | None
    if first_ticket is not None and last_ticket is not None:
        active_days = (last_ticket - first_ticket).days + 1
    else:
        active_days = None

    unique_jobs = len(set().union(*(r.job_keys for r in rollups))) if rollups else 0
    unique_vendors = len(set().union(*(r.vendor_keys for r in rollups))) if rollups else 0
    unique_drivers = len(set().union(*(r.driver_keys for r in rollups))) if rollups else 0

    # Rental monthly cost for the summary — mirrors rental-in summary's
    # total_monthly_cost so it's visible as a KPI tile without another call.
    rental_monthly = 0.0
    for r in rentals:
        rate = _f(r.get("rate")) or 0.0
        if (r.get("rate_unit") or "").strip().lower() == "monthly":
            rental_monthly += rate

    return FleetSummary(
        total_trucks=total_trucks,
        total_tickets=total_tickets,
        total_qty=total_qty,
        total_revenue=total_revenue,
        invoiced_revenue=invoiced_rev,
        uninvoiced_revenue=uninvoiced_rev,
        invoice_rate=invoice_rate,
        owned_trucks=owned,
        lessor_trucks=lessor,
        mixed_trucks=mixed,
        unknown_ownership_trucks=unknown,
        first_ticket=first_ticket,
        last_ticket=last_ticket,
        active_days=active_days,
        unique_jobs=unique_jobs,
        unique_vendors=unique_vendors,
        unique_drivers=unique_drivers,
        rental_contracts=len(rentals),
        rental_monthly_cost=rental_monthly,
    )


def list_trucks(
    engine: Engine,
    tenant_id: str,
    *,
    page: int = 1,
    page_size: int = 25,
    sort_by: SortField = "revenue",
    sort_dir: SortDir = "desc",
    lessor_flag: LessorFlag | None = None,
    invoice_bucket: InvoiceBucket | None = None,
    utilization_bucket: UtilizationBucket | None = None,
    search: str | None = None,
    underutilized_max_tickets: int = DEFAULT_UNDERUTILIZED_MAX_TICKETS,
    heavily_utilized_min_tickets: int = DEFAULT_HEAVILY_UTILIZED_MIN_TICKETS,
) -> TruckListResponse:
    """Paginated, filterable, sortable truck list."""
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 500:
        page_size = 25
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"

    util = _fetch_utilization(engine, tenant_id)
    rollups = _rollup(
        util,
        underutilized_max=underutilized_max_tickets,
        heavily_min=heavily_utilized_min_tickets,
    )

    rows = [
        _to_list_row(
            r,
            underutilized_max=underutilized_max_tickets,
            heavily_min=heavily_utilized_min_tickets,
        )
        for r in rollups
    ]

    if lessor_flag is not None:
        rows = [r for r in rows if r.lessor_flag is lessor_flag]
    if invoice_bucket is not None:
        rows = [r for r in rows if r.invoice_bucket is invoice_bucket]
    if utilization_bucket is not None:
        rows = [r for r in rows if r.utilization_bucket is utilization_bucket]
    if search:
        needle = search.lower()
        rows = [
            r for r in rows
            if needle in r.truck.lower()
            or (r.top_vendor and needle in r.top_vendor.lower())
            or (r.top_material and needle in r.top_material.lower())
            or (r.top_driver and needle in r.top_driver.lower())
            or (r.top_job and needle in r.top_job.lower())
        ]

    # Nones always last, regardless of direction.
    reverse = sort_dir == "desc"
    non_null = [r for r in rows if getattr(r, sort_by, None) is not None]
    null_rows = [r for r in rows if getattr(r, sort_by, None) is None]
    non_null.sort(key=lambda r: getattr(r, sort_by), reverse=reverse)
    rows = non_null + null_rows

    total = len(rows)
    start = (page - 1) * page_size
    items = rows[start:start + page_size]

    return TruckListResponse(
        total=total,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        items=items,
    )


def _mix_rows(
    counter: Counter,
    revenue_map: dict[str, float],
    qty_map: dict[str, float],
    *,
    limit: int,
) -> list[FleetMixRow]:
    return [
        FleetMixRow(
            label=label,
            ticket_count=count,
            revenue=revenue_map.get(label, 0.0),
            qty=qty_map.get(label, 0.0),
        )
        for label, count in counter.most_common(limit)
    ]


def _monthly_series(tickets: list[dict]) -> list[FleetMonthlyPoint]:
    buckets: dict[datetime, list[dict]] = defaultdict(list)
    for t in tickets:
        dt = _normalize_dt(t.get("ticket_date"))
        if dt is None:
            continue
        key = datetime(dt.year, dt.month, 1)
        buckets[key].append(t)

    out: list[FleetMonthlyPoint] = []
    for month in sorted(buckets.keys()):
        rows = buckets[month]
        out.append(
            FleetMonthlyPoint(
                month=month,
                ticket_count=len(rows),
                revenue=sum(_f(r.get("extended_price")) or 0.0 for r in rows),
                qty=sum(_f(r.get("qty")) or 0.0 for r in rows),
            )
        )
    return out


def get_truck_detail(
    engine: Engine,
    tenant_id: str,
    truck_id: str,
    *,
    underutilized_max_tickets: int = DEFAULT_UNDERUTILIZED_MAX_TICKETS,
    heavily_utilized_min_tickets: int = DEFAULT_HEAVILY_UTILIZED_MIN_TICKETS,
    recent_limit: int = DEFAULT_RECENT_TICKETS,
    mix_limit: int = DEFAULT_MIX_LIMIT,
) -> FleetTruckDetail | None:
    """Detail view for a single truck."""
    key = (truck_id or "").strip()
    if not key:
        return None

    util = _fetch_utilization(engine, tenant_id)
    matching = [r for r in util if (r.get("truck") or "").strip() == key]
    if not matching:
        return None

    rollup = _TruckRollup(truck=key, tickets=matching)
    rollup.finalize()

    list_row = _to_list_row(
        rollup,
        underutilized_max=underutilized_max_tickets,
        heavily_min=heavily_utilized_min_tickets,
    )

    # Recent tickets — sort by date desc, fall back to whatever order.
    def _ticket_dt(t: dict) -> datetime:
        dt = _normalize_dt(t.get("ticket_date"))
        return dt or datetime.min

    recent = sorted(matching, key=_ticket_dt, reverse=True)[:recent_limit]
    recent_points = [
        FleetTicketPoint(
            ticket=t.get("ticket"),
            ticket_date=_normalize_dt(t.get("ticket_date")),
            job=_strip_job_key(t.get("job")),
            vendor=(t.get("vendor") or None),
            pit=(t.get("pit") or None),
            material=(t.get("material") or None),
            driver=(t.get("driver") or None),
            qty=_f(t.get("qty")),
            units=(t.get("units") or None),
            price=_f(t.get("price")),
            extended_price=_f(t.get("extended_price")),
            invoiced=_bool(t.get("invoiced")),
            invoice_number=(t.get("invoice_number") or None),
        )
        for t in recent
    ]

    return FleetTruckDetail(
        id=list_row.id,
        truck=list_row.truck,
        ticket_count=list_row.ticket_count,
        total_qty=list_row.total_qty,
        revenue=list_row.revenue,
        avg_price_per_ticket=list_row.avg_price_per_ticket,
        invoiced_count=list_row.invoiced_count,
        invoiced_revenue=list_row.invoiced_revenue,
        uninvoiced_revenue=list_row.uninvoiced_revenue,
        invoice_rate=list_row.invoice_rate,
        jobs_served=list_row.jobs_served,
        vendors_served=list_row.vendors_served,
        first_ticket=list_row.first_ticket,
        last_ticket=list_row.last_ticket,
        active_days=list_row.active_days,
        lessor_flag=list_row.lessor_flag,
        invoice_bucket=list_row.invoice_bucket,
        utilization_bucket=list_row.utilization_bucket,
        top_material=list_row.top_material,
        top_vendor=list_row.top_vendor,
        top_job=list_row.top_job,
        top_driver=list_row.top_driver,
        recent_tickets=recent_points,
        monthly_series=_monthly_series(matching),
        vendor_mix=_mix_rows(
            rollup.vendor_counter, rollup.vendor_revenue,
            rollup.vendor_qty, limit=mix_limit,
        ),
        material_mix=_mix_rows(
            rollup.material_counter, rollup.material_revenue,
            rollup.material_qty, limit=mix_limit,
        ),
        job_mix=_mix_rows(
            rollup.job_counter, rollup.job_revenue,
            rollup.job_qty, limit=mix_limit,
        ),
        driver_mix=_mix_rows(
            rollup.driver_counter, rollup.driver_revenue,
            rollup.driver_qty, limit=mix_limit,
        ),
    )


def get_insights(
    engine: Engine,
    tenant_id: str,
    *,
    underutilized_max_tickets: int = DEFAULT_UNDERUTILIZED_MAX_TICKETS,
    heavily_utilized_min_tickets: int = DEFAULT_HEAVILY_UTILIZED_MIN_TICKETS,
    top_n: int = DEFAULT_TOP_N,
    now: datetime | None = None,
) -> FleetPnlInsights:
    """Precomputed fleet-wide analytics."""
    now_ = (now or datetime.now(timezone.utc)).replace(tzinfo=None)

    util = _fetch_utilization(engine, tenant_id)
    rentals = _fetch_rentals(engine, tenant_id)

    rollups = _rollup(
        util,
        underutilized_max=underutilized_max_tickets,
        heavily_min=heavily_utilized_min_tickets,
    )

    util_breakdown = UtilizationBreakdown(
        idle=sum(
            1 for r in rollups
            if _utilization_bucket(
                r.ticket_count, underutilized_max_tickets,
                heavily_utilized_min_tickets,
            ) is UtilizationBucket.IDLE
        ),
        underutilized=sum(
            1 for r in rollups
            if _utilization_bucket(
                r.ticket_count, underutilized_max_tickets,
                heavily_utilized_min_tickets,
            ) is UtilizationBucket.UNDERUTILIZED
        ),
        healthy=sum(
            1 for r in rollups
            if _utilization_bucket(
                r.ticket_count, underutilized_max_tickets,
                heavily_utilized_min_tickets,
            ) is UtilizationBucket.HEALTHY
        ),
        heavily_utilized=sum(
            1 for r in rollups
            if _utilization_bucket(
                r.ticket_count, underutilized_max_tickets,
                heavily_utilized_min_tickets,
            ) is UtilizationBucket.HEAVILY_UTILIZED
        ),
    )

    invoice_breakdown = InvoiceBreakdown(
        fully_invoiced=sum(
            1 for r in rollups
            if _invoice_bucket(
                r.invoiced_count, r.ticket_count, r.has_invoiced_data,
            ) is InvoiceBucket.FULLY_INVOICED
        ),
        partially_invoiced=sum(
            1 for r in rollups
            if _invoice_bucket(
                r.invoiced_count, r.ticket_count, r.has_invoiced_data,
            ) is InvoiceBucket.PARTIALLY_INVOICED
        ),
        uninvoiced=sum(
            1 for r in rollups
            if _invoice_bucket(
                r.invoiced_count, r.ticket_count, r.has_invoiced_data,
            ) is InvoiceBucket.UNINVOICED
        ),
        unknown=sum(
            1 for r in rollups
            if _invoice_bucket(
                r.invoiced_count, r.ticket_count, r.has_invoiced_data,
            ) is InvoiceBucket.UNKNOWN
        ),
    )

    def _money(r: _TruckRollup, value: float) -> TruckMoneyRow:
        return TruckMoneyRow(
            id=r.truck, truck=r.truck, value=value,
            ticket_count=r.ticket_count, revenue=r.revenue,
        )

    top_revenue = sorted(
        rollups, key=lambda r: r.revenue, reverse=True,
    )[:top_n]
    top_uninvoiced = sorted(
        (r for r in rollups if r.uninvoiced_revenue > 0),
        key=lambda r: r.uninvoiced_revenue, reverse=True,
    )[:top_n]
    top_underutilized = sorted(
        rollups, key=lambda r: r.ticket_count,
    )[:top_n]

    # Fleet-wide mix aggregation.
    vendor_counter: Counter = Counter()
    material_counter: Counter = Counter()
    job_counter: Counter = Counter()
    vendor_revenue: dict[str, float] = defaultdict(float)
    material_revenue: dict[str, float] = defaultdict(float)
    job_revenue: dict[str, float] = defaultdict(float)
    vendor_qty: dict[str, float] = defaultdict(float)
    material_qty: dict[str, float] = defaultdict(float)
    job_qty: dict[str, float] = defaultdict(float)

    for r in rollups:
        vendor_counter.update(r.vendor_counter)
        material_counter.update(r.material_counter)
        job_counter.update(r.job_counter)
        for k, v in r.vendor_revenue.items():
            vendor_revenue[k] += v
        for k, v in r.material_revenue.items():
            material_revenue[k] += v
        for k, v in r.job_revenue.items():
            job_revenue[k] += v
        for k, v in r.vendor_qty.items():
            vendor_qty[k] += v
        for k, v in r.material_qty.items():
            material_qty[k] += v
        for k, v in r.job_qty.items():
            job_qty[k] += v

    # Top mixes are ranked by revenue (P&L lens), not ticket count.
    top_vendor_rows = sorted(
        (
            FleetMixRow(
                label=v, ticket_count=vendor_counter[v],
                revenue=vendor_revenue[v], qty=vendor_qty[v],
            )
            for v in vendor_revenue
        ),
        key=lambda m: m.revenue,
        reverse=True,
    )[:top_n]
    top_material_rows = sorted(
        (
            FleetMixRow(
                label=v, ticket_count=material_counter[v],
                revenue=material_revenue[v], qty=material_qty[v],
            )
            for v in material_revenue
        ),
        key=lambda m: m.revenue,
        reverse=True,
    )[:top_n]
    top_job_rows = sorted(
        (
            FleetMixRow(
                label=v, ticket_count=job_counter[v],
                revenue=job_revenue[v], qty=job_qty[v],
            )
            for v in job_revenue
        ),
        key=lambda m: m.revenue,
        reverse=True,
    )[:top_n]

    return FleetPnlInsights(
        as_of=now_,
        underutilized_max_tickets=underutilized_max_tickets,
        heavily_utilized_min_tickets=heavily_utilized_min_tickets,
        utilization_breakdown=util_breakdown,
        invoice_breakdown=invoice_breakdown,
        rental_in=_rental_summary(rentals, top_n=top_n),
        top_revenue=[_money(r, r.revenue) for r in top_revenue],
        top_uninvoiced=[
            _money(r, r.uninvoiced_revenue) for r in top_uninvoiced
        ],
        top_underutilized=[
            _money(r, float(r.ticket_count)) for r in top_underutilized
        ],
        top_vendors=top_vendor_rows,
        top_materials=top_material_rows,
        top_jobs=top_job_rows,
    )
