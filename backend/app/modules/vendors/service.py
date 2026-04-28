"""Vendors service — pure query functions against the SQLite marts.

Reads a single mart:
  - mart_vendors  (~1.9k directory rows; ~32% null name, ~59% null email)

The mart has no transaction data, so the module surfaces *directory
health* metrics: firm-type mix, contact-data completeness, and CSI-
code coverage. IDs are normalized vendor names; rows with null name
get a synthetic ``__empty__<hash>`` ID so they remain addressable.

CSI code parsing: codes are stored as ``"NNNN-Description"`` strings
(e.g. ``"0330-Cast-in-place Concrete"``). The leading 4 digits are
MasterFormat; the first two are the division (e.g. ``"03"`` for
Concrete). ``_division`` extracts them.
"""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.modules.vendors.schema import (
    CodeMixRow,
    CodingBreakdown,
    CodingStatus,
    ContactHealthBreakdown,
    ContactStatus,
    DivisionMixRow,
    FirmType,
    FirmTypeBreakdown,
    VendorEnrichmentRequest,
    VendorDepthRow,
    VendorDetail,
    VendorListResponse,
    VendorListRow,
    VendorSummary,
    VendorsInsights,
)


# --------------------------------------------------------------------------- #
# Tunables                                                                    #
# --------------------------------------------------------------------------- #

# How many rows to return per top-N insight list.
DEFAULT_TOP_N = 10

# Divisions with vendor_count <= this surface in ``thin_divisions`` as
# candidate gaps to recruit into.
DEFAULT_THIN_DIVISION_MAX = 2
ENRICHMENTS_TABLE = "mart_vendor_enrichments"


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


SortField = Literal["name", "firm_type", "code_count", "primary_division"]
SortDir = Literal["asc", "desc"]


_FIRM_TYPE_MAP: dict[str, FirmType] = {
    "supplier": FirmType.SUPPLIER,
    "contractor": FirmType.CONTRACTOR,
    "service": FirmType.SERVICE,
    "internal": FirmType.INTERNAL,
}


def _norm_name(s: str | None) -> str | None:
    """Canonical vendor-id form — stripped & whitespace-collapsed."""
    if s is None:
        return None
    out = " ".join(s.split())
    return out or None


def _firm_type(raw: str | None) -> FirmType:
    if raw is None:
        return FirmType.UNKNOWN
    return _FIRM_TYPE_MAP.get(raw.strip().lower(), FirmType.UNKNOWN)


def _division(code: str | None) -> str | None:
    """Two-digit MasterFormat division from a vendor code string.

    ``"0330-Cast-in-place Concrete"`` → ``"03"``.
    ``"2600-Electrical"`` → ``"26"``.
    Returns None if the first two chars aren't digits.
    """
    if not code:
        return None
    s = code.strip()
    if len(s) < 2:
        return None
    prefix = s[:2]
    if not prefix.isdigit():
        return None
    return prefix


def _collect_codes(row: dict) -> list[str]:
    """Non-null, stripped, distinct codes from code_1..code_5."""
    seen: set[str] = set()
    out: list[str] = []
    for i in range(1, 6):
        raw = row.get(f"code_{i}")
        if raw is None:
            continue
        code = raw.strip()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _collect_enrichment_codes(row: dict) -> list[str]:
    """Non-null, stripped, distinct codes from enrichment e_code_1..e_code_5."""
    seen: set[str] = set()
    out: list[str] = []
    for i in range(1, 6):
        raw = row.get(f"e_code_{i}")
        if raw is None:
            continue
        code = raw.strip()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _contact_status(row: dict) -> ContactStatus:
    name = (row.get("name") or "").strip()
    if not name:
        return ContactStatus.EMPTY
    contact = (row.get("contact") or "").strip()
    email = (row.get("email") or "").strip()
    phone = (row.get("phone") or "").strip()
    filled = sum(1 for v in (contact, email, phone) if v)
    if filled >= 3:
        return ContactStatus.COMPLETE
    if filled >= 1:
        return ContactStatus.PARTIAL
    return ContactStatus.MINIMAL


def _coding_status(codes: list[str]) -> CodingStatus:
    return CodingStatus.CODED if codes else CodingStatus.UNCODED


def _vendor_id(row: dict) -> str:
    """Stable ID: normalized name, or synthetic for null-name rows.

    The mart carries a ``_row_hash`` column we can reuse, but stub
    rows don't always have it populated (older ingests). Fall back
    to hashing the available contact fields so the id is still
    deterministic.
    """
    name = _norm_name(row.get("name"))
    if name:
        return name
    rh = row.get("_row_hash")
    if rh:
        return f"__empty__{rh}"
    payload = "|".join(
        (row.get("contact") or "", row.get("email") or "", row.get("phone") or "")
    )
    digest = hashlib.md5(payload.encode("utf-8")).hexdigest()
    return f"__empty__{digest}"


def _clean_optional(value: str | None) -> str | None:
    """Trim optional text, returning None for blank strings."""
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _normalize_codes(codes: list[str]) -> list[str]:
    """Trim, dedupe, and cap enrichment code additions at five."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in codes:
        code = _clean_optional(raw)
        if code is None or code in seen:
            continue
        seen.add(code)
        out.append(code)
        if len(out) == 5:
            break
    return out


def _is_missing_enrichment_table(exc: DBAPIError) -> bool:
    msg = str(getattr(exc, "orig", exc)).lower()
    return ENRICHMENTS_TABLE in msg and (
        "no such table" in msg
        or "does not exist" in msg
        or "undefined table" in msg
    )


class VendorEnrichmentStoreMissing(RuntimeError):
    """Raised when the enrichment endpoint is used before Lead applies DDL."""


# --------------------------------------------------------------------------- #
# Rollup                                                                      #
# --------------------------------------------------------------------------- #


@dataclass
class _EnrichedRow:
    row: dict
    id: str
    name: str | None
    firm_type: FirmType
    firm_type_raw: str | None
    codes: list[str]
    divisions: list[str]
    primary_division: str | None
    contact_status: ContactStatus
    coding_status: CodingStatus
    enriched: bool = False
    enriched_at: str | None = None
    enrichment_notes: str | None = None

    @property
    def list_row(self) -> VendorListRow:
        return VendorListRow(
            id=self.id,
            name=self.name,
            firm_type=self.firm_type,
            firm_type_raw=self.firm_type_raw,
            contact=self.row.get("contact"),
            title=self.row.get("title"),
            email=self.row.get("email"),
            phone=self.row.get("phone"),
            codes=self.codes,
            code_count=len(self.codes),
            primary_division=self.primary_division,
            contact_status=self.contact_status,
            coding_status=self.coding_status,
            enriched=self.enriched,
            enriched_at=self.enriched_at,
        )


def _enrich(row: dict) -> _EnrichedRow:
    row = _merge_overlay(row)
    codes = _collect_codes(row)
    divisions = sorted({d for c in codes if (d := _division(c)) is not None})
    primary_division = _division(codes[0]) if codes else None
    raw = row.get("firm_type")
    return _EnrichedRow(
        row=row,
        id=_vendor_id(row),
        name=_norm_name(row.get("name")),
        firm_type=_firm_type(raw),
        firm_type_raw=raw,
        codes=codes,
        divisions=divisions,
        primary_division=primary_division,
        contact_status=_contact_status(row),
        coding_status=_coding_status(codes),
        enriched=bool(row.get("e_updated_at")),
        enriched_at=str(row["e_updated_at"]) if row.get("e_updated_at") else None,
        enrichment_notes=row.get("e_notes"),
    )


def _merge_overlay(row: dict) -> dict:
    """Merge mart_vendor_enrichments over mart_vendors without mutating input."""
    merged = dict(row)
    for field in ("contact", "title", "email", "phone", "firm_type"):
        override = _clean_optional(row.get(f"e_{field}"))
        if override is not None:
            merged[field] = override

    # Enrichment codes are additions. Keep base CSI codes first, then overlay
    # additions, capped at the five-code shape the current API exposes.
    combined = []
    seen: set[str] = set()
    for code in [*_collect_codes(row), *_collect_enrichment_codes(row)]:
        if code in seen:
            continue
        seen.add(code)
        combined.append(code)
        if len(combined) == 5:
            break
    for i in range(1, 6):
        merged[f"code_{i}"] = combined[i - 1] if i <= len(combined) else None
    return merged


# --------------------------------------------------------------------------- #
# SQL fetchers                                                                #
# --------------------------------------------------------------------------- #


def _fetch_all(engine: Engine, tenant_id: str) -> list[dict]:
    with engine.connect() as conn:
        try:
            rows = conn.execute(
                text(
                    """
                    SELECT v._row_hash, v.name, v.firm_type, v.contact, v.title,
                           v.email, v.phone, v.code_1, v.code_2, v.code_3,
                           v.code_4, v.code_5,
                           e.contact AS e_contact,
                           e.title AS e_title,
                           e.email AS e_email,
                           e.phone AS e_phone,
                           e.firm_type AS e_firm_type,
                           e.code_1 AS e_code_1,
                           e.code_2 AS e_code_2,
                           e.code_3 AS e_code_3,
                           e.code_4 AS e_code_4,
                           e.code_5 AS e_code_5,
                           e.notes AS e_notes,
                           e.updated_at AS e_updated_at
                    FROM mart_vendors v
                    LEFT JOIN mart_vendor_enrichments e
                      ON e.tenant_id = v.tenant_id
                     AND e.vendor_id = CASE
                         WHEN v.name IS NULL OR TRIM(v.name) = ''
                         THEN '__empty__' || v._row_hash
                         ELSE TRIM(v.name)
                     END
                    WHERE v.tenant_id = :tenant_id
                    """
                ),
                {"tenant_id": tenant_id},
            ).mappings().all()
        except DBAPIError as exc:
            if not _is_missing_enrichment_table(exc):
                raise
            rows = conn.execute(
                text(
                    """
                    SELECT _row_hash, name, firm_type, contact, title, email,
                           phone, code_1, code_2, code_3, code_4, code_5
                    FROM mart_vendors
                    WHERE tenant_id = :tenant_id
                    """
                ),
                {"tenant_id": tenant_id},
            ).mappings().all()
    return [dict(r) for r in rows]


def _vendor_exists(engine: Engine, tenant_id: str, vendor_id: str) -> bool:
    norm_key = _norm_name(vendor_id) or vendor_id
    for raw in _fetch_all(engine, tenant_id):
        enriched = _enrich(raw)
        if enriched.id == norm_key or enriched.id == vendor_id:
            return True
    return False


# --------------------------------------------------------------------------- #
# Public query API                                                            #
# --------------------------------------------------------------------------- #


def get_summary(engine: Engine, tenant_id: str) -> VendorSummary:
    rows = [_enrich(r) for r in _fetch_all(engine, tenant_id)]

    with_name = sum(1 for r in rows if r.name)
    with_contact = sum(1 for r in rows if (r.row.get("contact") or "").strip())
    with_email = sum(1 for r in rows if (r.row.get("email") or "").strip())
    with_phone = sum(1 for r in rows if (r.row.get("phone") or "").strip())
    complete_contact = sum(
        1 for r in rows if r.contact_status is ContactStatus.COMPLETE
    )

    coded = sum(1 for r in rows if r.coding_status is CodingStatus.CODED)
    uncoded = sum(1 for r in rows if r.coding_status is CodingStatus.UNCODED)

    all_codes: set[str] = set()
    all_divisions: set[str] = set()
    for r in rows:
        all_codes.update(r.codes)
        all_divisions.update(r.divisions)

    return VendorSummary(
        total_vendors=len(rows),
        with_name=with_name,
        with_contact=with_contact,
        with_email=with_email,
        with_phone=with_phone,
        complete_contact=complete_contact,
        coded_vendors=coded,
        uncoded_vendors=uncoded,
        distinct_codes=len(all_codes),
        distinct_divisions=len(all_divisions),
        suppliers=sum(1 for r in rows if r.firm_type is FirmType.SUPPLIER),
        contractors=sum(1 for r in rows if r.firm_type is FirmType.CONTRACTOR),
        services=sum(1 for r in rows if r.firm_type is FirmType.SERVICE),
        internal=sum(1 for r in rows if r.firm_type is FirmType.INTERNAL),
        unknown_firm_type=sum(
            1 for r in rows if r.firm_type is FirmType.UNKNOWN
        ),
    )


def list_vendors(
    engine: Engine,
    tenant_id: str,
    *,
    page: int = 1,
    page_size: int = 25,
    sort_by: SortField = "name",
    sort_dir: SortDir = "asc",
    firm_type: FirmType | None = None,
    contact_status: ContactStatus | None = None,
    coding_status: CodingStatus | None = None,
    division: str | None = None,
    search: str | None = None,
) -> VendorListResponse:
    """Paginated, filterable, sortable vendor list."""
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 500:
        page_size = 25
    if sort_dir not in ("asc", "desc"):
        sort_dir = "asc"

    enriched = [_enrich(r) for r in _fetch_all(engine, tenant_id)]
    rows = [e.list_row for e in enriched]

    if firm_type is not None:
        rows = [r for r in rows if r.firm_type is firm_type]
    if contact_status is not None:
        rows = [r for r in rows if r.contact_status is contact_status]
    if coding_status is not None:
        rows = [r for r in rows if r.coding_status is coding_status]
    if division is not None:
        needle = division.strip()
        if needle:
            rows = [
                r for r in rows
                if any(_division(c) == needle for c in r.codes)
            ]
    if search:
        needle = search.lower()
        rows = [
            r for r in rows
            if (r.name and needle in r.name.lower())
            or (r.contact and needle in r.contact.lower())
            or (r.email and needle in r.email.lower())
            or any(needle in c.lower() for c in r.codes)
        ]

    # Nones always last, regardless of direction.
    reverse = sort_dir == "desc"

    def _key(r: VendorListRow):
        val = getattr(r, sort_by, None)
        if sort_by in ("name", "primary_division") and isinstance(val, str):
            return val.lower()
        if sort_by == "firm_type":
            return r.firm_type.value
        return val

    non_null = [r for r in rows if getattr(r, sort_by, None) is not None]
    null_rows = [r for r in rows if getattr(r, sort_by, None) is None]
    non_null.sort(key=_key, reverse=reverse)
    rows = non_null + null_rows

    total = len(rows)
    start = (page - 1) * page_size
    items = rows[start:start + page_size]

    return VendorListResponse(
        total=total,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        items=items,
    )


def get_vendor_detail(
    engine: Engine, tenant_id: str, vendor_id: str,
) -> VendorDetail | None:
    """Detail view for a single vendor (by normalized name or empty-id)."""
    key = (vendor_id or "").strip()
    if not key:
        return None

    # Exact-ID match first (name-normalized or __empty__<hash>).
    norm_key = _norm_name(key) or key
    for raw in _fetch_all(engine, tenant_id):
        enriched = _enrich(raw)
        if enriched.id == norm_key or enriched.id == key:
            lr = enriched.list_row
            return VendorDetail(
                id=lr.id,
                name=lr.name,
                firm_type=lr.firm_type,
                firm_type_raw=lr.firm_type_raw,
                contact=lr.contact,
                title=lr.title,
                email=lr.email,
                phone=lr.phone,
                codes=lr.codes,
                code_count=lr.code_count,
                primary_division=lr.primary_division,
                divisions=enriched.divisions,
                contact_status=lr.contact_status,
                coding_status=lr.coding_status,
                enriched=enriched.enriched,
                enriched_at=enriched.enriched_at,
                enrichment_notes=enriched.enrichment_notes,
            )
    return None


def enrich_vendor(
    engine: Engine,
    tenant_id: str,
    vendor_id: str,
    payload: VendorEnrichmentRequest,
) -> VendorDetail | None:
    """Upsert a supplier-enrichment overlay and return the merged detail.

    Writes only to ``mart_vendor_enrichments``. The imported
    ``mart_vendors`` table and Vista ``apvend`` remain read-only in v1.
    """
    key = _norm_name(vendor_id) or vendor_id
    if not key:
        return None
    if not _vendor_exists(engine, tenant_id, key):
        return None

    codes = _normalize_codes(payload.codes)
    cleaned = {
        "contact": _clean_optional(payload.contact),
        "title": _clean_optional(payload.title),
        "email": _clean_optional(payload.email),
        "phone": _clean_optional(payload.phone),
        "firm_type": payload.firm_type.value if payload.firm_type else None,
        "notes": _clean_optional(payload.notes),
    }
    if not any(cleaned.values()) and not codes:
        raise ValueError("At least one enrichment field is required.")

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    params = {
        "tenant_id": tenant_id,
        "vendor_id": key,
        **cleaned,
        "code_1": codes[0] if len(codes) > 0 else None,
        "code_2": codes[1] if len(codes) > 1 else None,
        "code_3": codes[2] if len(codes) > 2 else None,
        "code_4": codes[3] if len(codes) > 3 else None,
        "code_5": codes[4] if len(codes) > 4 else None,
        "created_at": now,
        "updated_at": now,
    }

    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO mart_vendor_enrichments
                        (tenant_id, vendor_id, contact, title, email, phone,
                         firm_type, code_1, code_2, code_3, code_4, code_5,
                         notes, created_at, updated_at)
                    VALUES
                        (:tenant_id, :vendor_id, :contact, :title, :email,
                         :phone, :firm_type, :code_1, :code_2, :code_3,
                         :code_4, :code_5, :notes, :created_at, :updated_at)
                    ON CONFLICT (tenant_id, vendor_id) DO UPDATE SET
                        contact = excluded.contact,
                        title = excluded.title,
                        email = excluded.email,
                        phone = excluded.phone,
                        firm_type = excluded.firm_type,
                        code_1 = excluded.code_1,
                        code_2 = excluded.code_2,
                        code_3 = excluded.code_3,
                        code_4 = excluded.code_4,
                        code_5 = excluded.code_5,
                        notes = excluded.notes,
                        updated_at = excluded.updated_at
                    """
                ),
                params,
            )
    except DBAPIError as exc:
        if _is_missing_enrichment_table(exc):
            raise VendorEnrichmentStoreMissing(
                "mart_vendor_enrichments is missing. Lead must apply the "
                "vendors PROPOSED_CHANGES.md migration."
            ) from exc
        raise

    return get_vendor_detail(engine, tenant_id, key)


def get_insights(
    engine: Engine,
    tenant_id: str,
    *,
    top_n: int = DEFAULT_TOP_N,
    thin_division_max: int = DEFAULT_THIN_DIVISION_MAX,
) -> VendorsInsights:
    """Precomputed analytics — firm mix, contact health, CSI coverage."""
    enriched = [_enrich(r) for r in _fetch_all(engine, tenant_id)]

    firm_counts = Counter(e.firm_type for e in enriched)
    firm_breakdown = FirmTypeBreakdown(
        supplier=firm_counts.get(FirmType.SUPPLIER, 0),
        contractor=firm_counts.get(FirmType.CONTRACTOR, 0),
        service=firm_counts.get(FirmType.SERVICE, 0),
        internal=firm_counts.get(FirmType.INTERNAL, 0),
        unknown=firm_counts.get(FirmType.UNKNOWN, 0),
    )

    contact_counts = Counter(e.contact_status for e in enriched)
    contact_health = ContactHealthBreakdown(
        complete=contact_counts.get(ContactStatus.COMPLETE, 0),
        partial=contact_counts.get(ContactStatus.PARTIAL, 0),
        minimal=contact_counts.get(ContactStatus.MINIMAL, 0),
        empty=contact_counts.get(ContactStatus.EMPTY, 0),
    )

    coding_counts = Counter(e.coding_status for e in enriched)
    coding = CodingBreakdown(
        coded=coding_counts.get(CodingStatus.CODED, 0),
        uncoded=coding_counts.get(CodingStatus.UNCODED, 0),
    )

    # Code frequency across vendors (each vendor counts once per code).
    code_vendor_count: Counter = Counter()
    code_firm_type_counts: dict[str, Counter] = defaultdict(Counter)
    for e in enriched:
        for c in e.codes:
            code_vendor_count[c] += 1
            code_firm_type_counts[c][e.firm_type] += 1

    top_codes_raw = code_vendor_count.most_common(top_n)
    top_codes = [
        CodeMixRow(
            code=c,
            vendor_count=count,
            top_firm_type=(
                code_firm_type_counts[c].most_common(1)[0][0]
                if code_firm_type_counts[c] else FirmType.UNKNOWN
            ),
        )
        for c, count in top_codes_raw
    ]

    # Division rollup — vendor_count distinct, code_count cumulative.
    division_vendors: dict[str, set[str]] = defaultdict(set)
    division_code_count: Counter = Counter()
    division_example: dict[str, str] = {}
    for e in enriched:
        for c in e.codes:
            d = _division(c)
            if d is None:
                continue
            division_vendors[d].add(e.id)
            division_code_count[d] += 1
            division_example.setdefault(d, c)

    all_divisions = [
        DivisionMixRow(
            division=d,
            vendor_count=len(vendors),
            code_count=division_code_count[d],
            example_code=division_example.get(d),
        )
        for d, vendors in division_vendors.items()
    ]
    top_divisions = sorted(
        all_divisions, key=lambda m: m.vendor_count, reverse=True,
    )[:top_n]
    thin_divisions = sorted(
        (m for m in all_divisions if m.vendor_count <= thin_division_max),
        key=lambda m: (m.vendor_count, m.division),
    )

    depth_leaders_raw = sorted(
        (e for e in enriched if len(e.codes) >= 2),
        key=lambda e: (-len(e.codes), (e.name or "").lower()),
    )[:top_n]
    depth_leaders = [
        VendorDepthRow(
            id=e.id,
            name=e.name,
            code_count=len(e.codes),
            codes=e.codes,
            firm_type=e.firm_type,
        )
        for e in depth_leaders_raw
    ]

    return VendorsInsights(
        firm_type_breakdown=firm_breakdown,
        contact_health=contact_health,
        coding_breakdown=coding,
        top_codes=top_codes,
        top_divisions=top_divisions,
        thin_divisions=thin_divisions,
        depth_leaders=depth_leaders,
    )
