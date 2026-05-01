"""Equipment service — pure query functions against the SQLite marts.

Every function takes an ``Engine`` explicitly and returns plain
dicts/Pydantic models — no FastAPI types, no global DB state, no tenant
lookup magic. That makes the module trivially testable: pass an engine
from a fixture and assert on the return value.

Reads from:
  - mart_equipment_utilization   (per-ticket utilization)
  - mart_equipment_rentals       (third-party rentals)
  - mart_asset_barcodes          (asset master / retirement)

The mart -> Vista v2 graduation keeps these column shapes stable; see
``fieldbridge/docs/data_mapping.md``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import Engine, text

from app.modules.equipment.schema import (
    BucketBreakdown,
    EquipmentCurrentJob,
    EquipmentDetail,
    EquipmentInsights,
    EquipmentListResponse,
    EquipmentListRow,
    EquipmentLastTransfer,
    EquipmentStatusResponse,
    EquipmentStatusRow,
    EquipmentSummary,
    FuelCostPerHour,
    OwnershipKind,
    OwnershipMetrics,
    RecentTicket,
    RentalMetrics,
    RentalVsOwned,
    UtilizationBucket,
)


# --------------------------------------------------------------------------- #
# Tunable thresholds                                                          #
# --------------------------------------------------------------------------- #

# "Weekly ticket rate" buckets. Deliberately conservative; a real deployment
# should calibrate these off 90-day history for the target fleet.
UNDER_WEEKLY_MAX = 5.0     # < 5 tickets/week => under-utilized
EXCESSIVE_WEEKLY_MIN = 50.0  # >= 50 tickets/week => excessive

# "Issues" supersedes the other buckets.
STALE_DAYS_ISSUES = 60      # no ticket in this many days + retired asset
STALE_TICKET_DAYS = 14       # field alert lane: no ticket, not yet retired
HOUR_UNIT_TOKENS = {"hr", "hrs", "hour", "hours"}


SortField = Literal["truck", "tickets", "total_qty", "total_revenue", "last_ticket_date"]
SortDir = Literal["asc", "desc"]

_SORT_COLUMNS: dict[str, str] = {
    "truck": "truck",
    "tickets": "tickets",
    "total_qty": "total_qty",
    "total_revenue": "total_revenue",
    "last_ticket_date": "last_ticket_date",
}


# --------------------------------------------------------------------------- #
# Internal helpers                                                            #
# --------------------------------------------------------------------------- #


def _agg_sql() -> str:
    """Per-truck aggregate from ``mart_equipment_utilization``.

    Uses an LOWER() match on the ``units`` column to estimate hours logged
    so we can compute a cost-per-hour proxy for the insights endpoint.
    """
    hour_tokens = ", ".join(f"'{t}'" for t in sorted(HOUR_UNIT_TOKENS))
    return f"""
    SELECT
        truck,
        COUNT(*)                                              AS tickets,
        COALESCE(SUM(qty), 0)                                 AS total_qty,
        COALESCE(SUM(extended_price), 0)                      AS total_revenue,
        MIN(ticket_date)                                      AS first_ticket_date,
        MAX(ticket_date)                                      AS last_ticket_date,
        COALESCE(SUM(
            CASE WHEN LOWER(TRIM(COALESCE(units,''))) IN ({hour_tokens})
                 THEN qty ELSE 0 END
        ), 0)                                                 AS hours_logged
    FROM mart_equipment_utilization
    WHERE tenant_id = :tenant_id
    GROUP BY truck
    """


def _rental_lookup(engine: Engine, tenant_id: str) -> dict[str, dict]:
    """Map equipment name -> most recent rental row (or {} if none)."""
    rows = engine.connect().execute(
        text(
            """
            SELECT equipment, rental_company, picked_up_date,
                   scheduled_return_date, returned_date, rate, rate_unit
            FROM mart_equipment_rentals
            WHERE tenant_id = :tenant_id
            ORDER BY picked_up_date DESC
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()

    out: dict[str, dict] = {}
    for r in rows:
        if r["equipment"] not in out:
            out[r["equipment"]] = dict(r)
    return out


def _asset_master(engine: Engine, tenant_id: str) -> dict[str, dict]:
    """Map str(barcode) -> asset master row."""
    rows = engine.connect().execute(
        text(
            """
            SELECT barcode, manufacturer, material, model, retired_date
            FROM mart_asset_barcodes
            WHERE tenant_id = :tenant_id
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    return {str(r["barcode"]): dict(r) for r in rows}


def _work_order_status(code: str | None) -> Literal["open", "hold", "closed", "unknown"]:
    """Normalize Vista emwo.Status codes from mart_work_orders."""
    if code is None:
        return "unknown"
    return {
        "O": "open",
        "H": "hold",
        "C": "closed",
    }.get(str(code).strip().upper(), "unknown")


def _current_job_lookup(engine: Engine, tenant_id: str) -> dict[str, EquipmentCurrentJob]:
    """Map equipment name -> best current mart_work_orders/emwo row.

    Open rows win over hold rows, which win over closed/unknown history. Within
    that status priority, the newest open_date is treated as current.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT equipment, work_order, status, open_date, description,
                       job_number
                FROM mart_work_orders
                WHERE tenant_id = :tenant_id
                  AND equipment IS NOT NULL
                  AND TRIM(equipment) != ''
                ORDER BY equipment ASC,
                         CASE UPPER(TRIM(COALESCE(status, '')))
                             WHEN 'O' THEN 0
                             WHEN 'H' THEN 1
                             WHEN 'C' THEN 2
                             ELSE 3
                         END ASC,
                         open_date DESC
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()

    out: dict[str, EquipmentCurrentJob] = {}
    for r in rows:
        equipment = str(r["equipment"])
        if equipment in out:
            continue
        out[equipment] = EquipmentCurrentJob(
            job_number=r.get("job_number"),
            work_order=str(r["work_order"]) if r.get("work_order") is not None else None,
            status=_work_order_status(r.get("status")),
            open_date=_normalize_dt(r.get("open_date")),
            description=r.get("description"),
        )
    return out


def _last_transfer_lookup(engine: Engine, tenant_id: str) -> dict[str, EquipmentLastTransfer]:
    """Map equipment/tool name -> latest mart_equipment_transfers row."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT tool_consumable, transfer_date, location, quantity,
                       requested_by, user
                FROM mart_equipment_transfers
                WHERE tenant_id = :tenant_id
                  AND tool_consumable IS NOT NULL
                  AND TRIM(tool_consumable) != ''
                ORDER BY transfer_date DESC
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()

    out: dict[str, EquipmentLastTransfer] = {}
    for r in rows:
        asset = str(r["tool_consumable"])
        if asset in out:
            continue
        out[asset] = EquipmentLastTransfer(
            transfer_date=_normalize_dt(r.get("transfer_date")),
            location=r.get("location"),
            quantity=(int(r["quantity"]) if r.get("quantity") is not None else None),
            requested_by=r.get("requested_by"),
            user=r.get("user"),
        )
    return out


def _normalize_dt(v) -> datetime | None:
    """SQLite stores DateTime as ISO strings; normalize back to datetime."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


def classify_bucket(
    tickets: int,
    first_ticket: datetime | None,
    last_ticket: datetime | None,
    retired_date: datetime | None,
    *,
    now: datetime | None = None,
) -> UtilizationBucket:
    """Pure function so it's trivially unit-testable and documented in one place.

    Order matters:
      1. ``issues``     — retired, or stale (no activity in 60d)
      2. ``excessive``  — >= 50 tickets/week on average
      3. ``under``      — < 5 tickets/week on average
      4. ``good``       — otherwise
    """
    now = now or datetime.now(timezone.utc)
    # Strip tz so comparisons with naive SQLite values work.
    now = now.replace(tzinfo=None)

    if retired_date is not None:
        return UtilizationBucket.ISSUES
    if last_ticket is not None and (now - last_ticket).days >= STALE_DAYS_ISSUES:
        return UtilizationBucket.ISSUES

    if first_ticket and last_ticket and tickets > 0:
        span_days = max((last_ticket - first_ticket).days + 1, 1)
        weekly = tickets * 7.0 / span_days
    else:
        weekly = 0.0

    if weekly >= EXCESSIVE_WEEKLY_MIN:
        return UtilizationBucket.EXCESSIVE
    if weekly < UNDER_WEEKLY_MAX:
        return UtilizationBucket.UNDER
    return UtilizationBucket.GOOD


# --------------------------------------------------------------------------- #
# Public query API                                                            #
# --------------------------------------------------------------------------- #


def get_summary(
    engine: Engine,
    tenant_id: str,
    *,
    now: datetime | None = None,
) -> EquipmentSummary:
    """KPI tiles. Runs one aggregate per tile, not per-row."""
    now = now or datetime.now(timezone.utc)
    now_naive = now.replace(tzinfo=None)

    rentals = _rental_lookup(engine, tenant_id)
    asset_master = _asset_master(engine, tenant_id)
    retired = {
        k for k, v in asset_master.items()
        if _normalize_dt(v.get("retired_date")) is not None
    }

    with engine.connect() as conn:
        aggs = conn.execute(
            text(_agg_sql()), {"tenant_id": tenant_id}
        ).mappings().all()

        window_start = (now_naive - timedelta(days=30)).isoformat()
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

    under = excessive = good = issues = 0
    owned = rented = 0
    for row in aggs:
        truck = row["truck"]
        first = _normalize_dt(row["first_ticket_date"])
        last = _normalize_dt(row["last_ticket_date"])
        retired_dt = _normalize_dt(
            asset_master.get(truck, {}).get("retired_date")
        )
        # Allow the retired set to force-issue even when we didn't find a
        # barcode match (truck name doubles as asset id for some shops).
        if truck in retired:
            retired_dt = retired_dt or now_naive

        bucket = classify_bucket(
            int(row["tickets"]), first, last, retired_dt, now=now,
        )
        if bucket is UtilizationBucket.UNDER:
            under += 1
        elif bucket is UtilizationBucket.EXCESSIVE:
            excessive += 1
        elif bucket is UtilizationBucket.GOOD:
            good += 1
        else:
            issues += 1

        if truck in rentals:
            rented += 1
        else:
            owned += 1

    return EquipmentSummary(
        total_assets=owned + rented,
        owned_assets=owned,
        rented_assets=rented,
        tickets_30d=int(tickets_30d or 0),
        revenue_30d=float(revenue_30d or 0.0),
        bucket_under=under,
        bucket_excessive=excessive,
        bucket_good=good,
        bucket_issues=issues,
    )


def list_equipment(
    engine: Engine,
    tenant_id: str,
    *,
    page: int = 1,
    page_size: int = 25,
    sort_by: SortField = "last_ticket_date",
    sort_dir: SortDir = "desc",
    search: str | None = None,
    bucket_filter: UtilizationBucket | None = None,
    ownership_filter: OwnershipKind | None = None,
    now: datetime | None = None,
) -> EquipmentListResponse:
    """Paginated, filtered, sorted list of equipment.

    We aggregate in SQL, then filter by bucket/ownership in Python because
    the bucket classification depends on the asset-master join (retired) and
    the rentals lookup — cheaper to compute once than to do three joins.
    """
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 500:
        page_size = 25
    if sort_by not in _SORT_COLUMNS:
        sort_by = "last_ticket_date"
    sort_dir = "desc" if sort_dir not in ("asc", "desc") else sort_dir

    rentals = _rental_lookup(engine, tenant_id)
    asset_master = _asset_master(engine, tenant_id)

    with engine.connect() as conn:
        rows = conn.execute(
            text(_agg_sql()), {"tenant_id": tenant_id}
        ).mappings().all()

    enriched: list[EquipmentListRow] = []
    for row in rows:
        truck = row["truck"]
        if search and search.lower() not in truck.lower():
            continue

        first = _normalize_dt(row["first_ticket_date"])
        last = _normalize_dt(row["last_ticket_date"])
        retired_dt = _normalize_dt(
            asset_master.get(truck, {}).get("retired_date")
        )
        bucket = classify_bucket(
            int(row["tickets"]), first, last, retired_dt, now=now,
        )
        ownership = (
            OwnershipKind.RENTED if truck in rentals else OwnershipKind.OWNED
        )

        if bucket_filter is not None and bucket is not bucket_filter:
            continue
        if ownership_filter is not None and ownership is not ownership_filter:
            continue

        enriched.append(
            EquipmentListRow(
                id=truck,
                truck=truck,
                ownership=ownership,
                tickets=int(row["tickets"] or 0),
                total_qty=float(row["total_qty"] or 0.0),
                total_revenue=float(row["total_revenue"] or 0.0),
                last_ticket_date=last,
                bucket=bucket,
            )
        )

    reverse = sort_dir == "desc"
    key = _SORT_COLUMNS[sort_by]

    def _sort_key(r: EquipmentListRow):
        v = getattr(r, key)
        # None sorts last under desc, first under asc — match a reasonable UI.
        return (v is None, v)

    enriched.sort(key=_sort_key, reverse=reverse)

    total = len(enriched)
    start = (page - 1) * page_size
    items = enriched[start:start + page_size]

    return EquipmentListResponse(
        total=total,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        items=items,
    )


def get_status_board(
    engine: Engine,
    tenant_id: str,
    *,
    page: int = 1,
    page_size: int = 100,
    search: str | None = None,
    bucket_filter: UtilizationBucket | None = None,
    stale_only: bool = False,
    include_retired: bool = True,
    now: datetime | None = None,
) -> EquipmentStatusResponse:
    """Field-facing live asset status board.

    Reads mart_equipment_utilization for utilization recency, joins the best
    current emwo context from mart_work_orders, pulls movement recency from
    mart_equipment_transfers, and marks retirement from mart_asset_barcodes.
    """
    now = now or datetime.now(timezone.utc)
    now_naive = now.replace(tzinfo=None)
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 500:
        page_size = 100

    rentals = _rental_lookup(engine, tenant_id)
    asset_master = _asset_master(engine, tenant_id)
    jobs = _current_job_lookup(engine, tenant_id)
    transfers = _last_transfer_lookup(engine, tenant_id)

    with engine.connect() as conn:
        utilization_rows = conn.execute(
            text(_agg_sql()), {"tenant_id": tenant_id}
        ).mappings().all()

    utilization_by_truck = {str(r["truck"]): dict(r) for r in utilization_rows}
    asset_ids = (
        set(utilization_by_truck)
        | set(rentals)
        | set(asset_master)
        | set(jobs)
        | set(transfers)
    )

    rows: list[EquipmentStatusRow] = []
    for asset_id in asset_ids:
        if search and search.lower() not in asset_id.lower():
            continue

        agg = utilization_by_truck.get(
            asset_id,
            {
                "truck": asset_id,
                "tickets": 0,
                "total_qty": 0.0,
                "total_revenue": 0.0,
                "first_ticket_date": None,
                "last_ticket_date": None,
                "hours_logged": 0.0,
            },
        )
        first = _normalize_dt(agg.get("first_ticket_date"))
        last = _normalize_dt(agg.get("last_ticket_date"))
        master = asset_master.get(asset_id, {})
        retired_dt = _normalize_dt(master.get("retired_date"))
        retired = retired_dt is not None
        if retired and not include_retired:
            continue

        bucket = classify_bucket(
            int(agg.get("tickets") or 0), first, last, retired_dt, now=now,
        )
        if bucket_filter is not None and bucket is not bucket_filter:
            continue

        days_since_last = (now_naive - last).days if last is not None else None
        stale_ticket = (
            not retired
            and (days_since_last is None or days_since_last >= STALE_TICKET_DAYS)
        )
        if stale_only and not stale_ticket:
            continue

        ownership = OwnershipKind.RENTED if asset_id in rentals else OwnershipKind.OWNED
        rows.append(
            EquipmentStatusRow(
                id=asset_id,
                truck=asset_id,
                bucket=bucket,
                ownership=ownership,
                retired=retired,
                retired_date=retired_dt,
                tickets=int(agg.get("tickets") or 0),
                last_ticket_date=last,
                days_since_last_ticket=days_since_last,
                stale_ticket=stale_ticket,
                current_job=jobs.get(asset_id, EquipmentCurrentJob()),
                last_transfer=transfers.get(asset_id, EquipmentLastTransfer()),
            )
        )

    bucket_rank = {
        UtilizationBucket.ISSUES: 0,
        UtilizationBucket.EXCESSIVE: 1,
        UtilizationBucket.UNDER: 2,
        UtilizationBucket.GOOD: 3,
    }
    rows.sort(
        key=lambda r: (
            not r.stale_ticket,
            r.retired,
            bucket_rank[r.bucket],
            -(r.days_since_last_ticket or -1),
            r.truck.lower(),
        )
    )

    total = len(rows)
    start = (page - 1) * page_size
    return EquipmentStatusResponse(
        as_of=now,
        stale_threshold_days=STALE_TICKET_DAYS,
        total=total,
        page=page,
        page_size=page_size,
        items=rows[start:start + page_size],
    )


def get_equipment_detail(
    engine: Engine,
    tenant_id: str,
    asset_id: str,
    *,
    now: datetime | None = None,
    recent_limit: int = 10,
) -> EquipmentDetail | None:
    """Detail for a single asset (keyed by truck name)."""
    rentals = _rental_lookup(engine, tenant_id)
    asset_master = _asset_master(engine, tenant_id)

    with engine.connect() as conn:
        agg = conn.execute(
            text(_agg_sql() + " HAVING truck = :truck"),
            {"tenant_id": tenant_id, "truck": asset_id},
        ).mappings().one_or_none()

        if agg is None:
            # Allow the detail endpoint to still return something for a
            # rental-only or master-only asset (never shipped a ticket).
            if asset_id not in rentals and asset_id not in asset_master:
                return None
            agg = {
                "truck": asset_id,
                "tickets": 0,
                "total_qty": 0.0,
                "total_revenue": 0.0,
                "first_ticket_date": None,
                "last_ticket_date": None,
                "hours_logged": 0.0,
            }

        recent = conn.execute(
            text(
                """
                SELECT ticket_date, ticket, job, material, qty, units,
                       price, extended_price
                FROM mart_equipment_utilization
                WHERE tenant_id = :tenant_id AND truck = :truck
                ORDER BY ticket_date DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": tenant_id, "truck": asset_id, "limit": recent_limit},
        ).mappings().all()

    first = _normalize_dt(agg["first_ticket_date"])
    last = _normalize_dt(agg["last_ticket_date"])
    master = asset_master.get(asset_id, {})
    retired_dt = _normalize_dt(master.get("retired_date"))
    bucket = classify_bucket(
        int(agg["tickets"] or 0), first, last, retired_dt, now=now,
    )
    ownership = (
        OwnershipKind.RENTED if asset_id in rentals else OwnershipKind.OWNED
    )
    rental = rentals.get(asset_id, {})

    hours = float(agg["hours_logged"] or 0.0)
    revenue = float(agg["total_revenue"] or 0.0)
    cost_per_hour = revenue / hours if hours > 0 else None

    return EquipmentDetail(
        id=asset_id,
        truck=asset_id,
        ownership=ownership,
        bucket=bucket,
        tickets=int(agg["tickets"] or 0),
        total_qty=float(agg["total_qty"] or 0.0),
        total_revenue=revenue,
        first_ticket_date=first,
        last_ticket_date=last,
        cost_per_hour=cost_per_hour,
        manufacturer=master.get("manufacturer"),
        model=master.get("model"),
        material=master.get("material"),
        retired_date=retired_dt,
        rental_company=rental.get("rental_company") if rental else None,
        picked_up_date=_normalize_dt(rental.get("picked_up_date")) if rental else None,
        scheduled_return_date=_normalize_dt(rental.get("scheduled_return_date")) if rental else None,
        returned_date=_normalize_dt(rental.get("returned_date")) if rental else None,
        rental_rate=(float(rental["rate"])
                     if rental and rental.get("rate") is not None else None),
        rate_unit=rental.get("rate_unit") if rental else None,
        recent_tickets=[
            RecentTicket(
                ticket_date=_normalize_dt(r["ticket_date"]),
                ticket=str(r["ticket"]),
                job=r["job"],
                material=r["material"],
                qty=(float(r["qty"]) if r["qty"] is not None else None),
                units=r["units"],
                price=(float(r["price"]) if r["price"] is not None else None),
                extended_price=(float(r["extended_price"])
                                if r["extended_price"] is not None else None),
            )
            for r in recent
        ],
    )


def get_insights(
    engine: Engine,
    tenant_id: str,
    *,
    now: datetime | None = None,
    top_n: int = 20,
) -> EquipmentInsights:
    """Precomputed analytics for the Insights panel.

    Three payloads:
      * Utilization bucket counts (must match the four tiles on the screen).
      * Per-asset fuel $/hr proxy (revenue / hours logged) — ordered by hours.
      * Rental vs owned comparison.
    """
    now = now or datetime.now(timezone.utc)

    rentals = _rental_lookup(engine, tenant_id)
    asset_master = _asset_master(engine, tenant_id)

    with engine.connect() as conn:
        rows = conn.execute(
            text(_agg_sql()), {"tenant_id": tenant_id}
        ).mappings().all()

    under = excessive = good = issues = 0
    fuel_rows: list[FuelCostPerHour] = []
    owned_tickets = rented_tickets = 0
    owned_revenue = 0.0
    owned_count = rented_count = 0

    for row in rows:
        truck = row["truck"]
        first = _normalize_dt(row["first_ticket_date"])
        last = _normalize_dt(row["last_ticket_date"])
        retired_dt = _normalize_dt(
            asset_master.get(truck, {}).get("retired_date")
        )
        bucket = classify_bucket(
            int(row["tickets"] or 0), first, last, retired_dt, now=now,
        )

        if bucket is UtilizationBucket.UNDER:
            under += 1
        elif bucket is UtilizationBucket.EXCESSIVE:
            excessive += 1
        elif bucket is UtilizationBucket.GOOD:
            good += 1
        else:
            issues += 1

        hours = float(row["hours_logged"] or 0.0)
        revenue = float(row["total_revenue"] or 0.0)
        if hours > 0:
            fuel_rows.append(
                FuelCostPerHour(
                    id=truck,
                    truck=truck,
                    hours=hours,
                    revenue=revenue,
                    cost_per_hour=revenue / hours,
                )
            )

        if truck in rentals:
            rented_count += 1
            rented_tickets += int(row["tickets"] or 0)
        else:
            owned_count += 1
            owned_tickets += int(row["tickets"] or 0)
            owned_revenue += revenue

    # Rentals-only assets (no utilization tickets yet) still count as rented.
    for eq in rentals:
        if eq not in {r["truck"] for r in rows}:
            rented_count += 1

    fuel_rows.sort(key=lambda r: r.hours, reverse=True)
    fuel_rows = fuel_rows[:top_n]

    # Rental side metrics
    active_rentals = sum(
        1 for r in rentals.values() if _normalize_dt(r.get("returned_date")) is None
    )
    rental_rates = [
        float(r["rate"]) for r in rentals.values()
        if r.get("rate") is not None
    ]
    total_rate_committed = sum(rental_rates)
    avg_rate = (total_rate_committed / len(rental_rates)) if rental_rates else 0.0

    owned_metrics = OwnershipMetrics(
        count=owned_count,
        total_revenue=owned_revenue,
        total_tickets=owned_tickets,
        avg_tickets_per_asset=(owned_tickets / owned_count) if owned_count else 0.0,
    )
    rented_metrics = RentalMetrics(
        count=rented_count,
        active_rentals=active_rentals,
        total_rate_committed=total_rate_committed,
        avg_rate=avg_rate,
    )

    return EquipmentInsights(
        as_of=now,
        utilization_buckets=BucketBreakdown(
            under=under, excessive=excessive, good=good, issues=issues,
        ),
        fuel_cost_per_hour_by_asset=fuel_rows,
        rental_vs_owned=RentalVsOwned(owned=owned_metrics, rented=rented_metrics),
    )
