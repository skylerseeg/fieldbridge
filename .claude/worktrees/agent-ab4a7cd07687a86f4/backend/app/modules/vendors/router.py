"""FastAPI router for the vendors module.

Endpoints (mounted at ``/api/vendors`` in ``app.main``):
    GET /summary        KPI tiles.
    GET /list           Paginated, filterable, sortable table.
    GET /{vendor_id}    Detail row.
    GET /insights       Precomputed analytics.

Vendor IDs are normalized (stripped / whitespace-collapsed) names.
Rows with null name fall back to ``__empty__<row_hash>``. The detail
route uses a path converter so names with slashes stay addressable.

Mirrors the equipment / work-orders / timecards / jobs / fleet_pnl
module pattern: two lightweight dependencies (``get_engine`` and
``get_tenant_id``) so tests can override them via
``app.dependency_overrides``.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.ingest import _sync_url
from app.core.llm import InsightResponse
from app.models.tenant import Tenant
from app.modules.vendors import insights as insights_pipeline
from app.modules.vendors import service
from app.modules.vendors.schema import (
    CodingStatus,
    ContactStatus,
    FirmType,
    VendorDetail,
    VendorEnrichmentRequest,
    VendorListResponse,
    VendorSummary,
    VendorsInsights,
)

log = logging.getLogger("fieldbridge.vendors")

router = APIRouter()


# --------------------------------------------------------------------------- #
# Dependencies (overridable in tests)                                         #
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def _default_engine() -> Engine:
    """Process-wide sync engine for mart reads.

    ``dependency_overrides`` in tests injects a test-specific engine, so
    this cache never becomes a problem in the test suite.
    """
    return create_engine(_sync_url(settings.database_url), pool_pre_ping=True)


def get_engine() -> Engine:
    """Default engine dependency. Override in tests."""
    return _default_engine()


def get_tenant_id(engine: Engine = Depends(get_engine)) -> str:
    """Resolve the request's tenant UUID.

    No auth yet on this module (read-only mart data); we default to the
    ``vancon`` reference tenant. When auth is added, swap this for
    ``app.core.auth.get_current_tenant`` and return ``tenant.id``.
    """
    SessionLocal = sessionmaker(engine)
    with SessionLocal() as s:
        tenant = s.execute(
            select(Tenant).where(Tenant.slug == "vancon")
        ).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(
            status_code=503,
            detail="Reference tenant not seeded. Run scripts/create_mart_tables.py.",
        )
    return tenant.id


# --------------------------------------------------------------------------- #
# Endpoints                                                                   #
# --------------------------------------------------------------------------- #


@router.get("/summary", response_model=VendorSummary)
def summary(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
) -> VendorSummary:
    """KPI tiles — totals, contact health, CSI coverage, firm mix."""
    return service.get_summary(engine, tenant_id)


@router.get("/list", response_model=VendorListResponse)
def list_(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
    sort_by: Literal[
        "name", "firm_type", "code_count", "primary_division",
    ] = "name",
    sort_dir: Literal["asc", "desc"] = "asc",
    firm_type: FirmType | None = Query(
        None, description="Filter by normalized firm type.",
    ),
    contact_status: ContactStatus | None = Query(
        None, description="Filter by contact-data completeness tier.",
    ),
    coding_status: CodingStatus | None = Query(
        None, description="Filter by CSI-coding status.",
    ),
    division: str | None = Query(
        None,
        description=(
            'Two-digit MasterFormat division filter (e.g. ``"03"``). '
            "Matches any of the vendor's codes."
        ),
        max_length=4,
    ),
    search: str | None = Query(
        None,
        description=(
            "Case-insensitive substring match on name, contact, email, "
            "or any CSI code."
        ),
    ),
) -> VendorListResponse:
    """Paginated vendor table with filters and sort."""
    return service.list_vendors(
        engine, tenant_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        firm_type=firm_type,
        contact_status=contact_status,
        coding_status=coding_status,
        division=division,
        search=search,
    )


@router.get("/insights", response_model=VendorsInsights)
def insights(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    top_n: int = Query(
        service.DEFAULT_TOP_N, ge=1, le=100,
        description="How many rows to return in each top-N list.",
    ),
    thin_division_max: int = Query(
        service.DEFAULT_THIN_DIVISION_MAX, ge=0, le=100,
        description=(
            "Divisions with ``vendor_count <= thin_division_max`` surface "
            "as recruitment gaps."
        ),
    ),
) -> VendorsInsights:
    """Precomputed analytics: firm mix, contact health, CSI coverage, depth leaders."""
    return service.get_insights(
        engine, tenant_id,
        top_n=top_n,
        thin_division_max=thin_division_max,
    )


@router.get("/recommendations", response_model=InsightResponse)
def recommendations(
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
    refresh: bool = Query(
        False,
        description=(
            "Bypass the 6h cache and force a fresh Claude call. Used by "
            "the admin Regenerate button — most callers should leave this "
            "false."
        ),
    ),
) -> InsightResponse:
    """Phase-6 LLM-generated vendor-bench recommendations.

    Cached for ``DEFAULT_TTL_HOURS`` (6h) per ``(tenant, module)``;
    re-runs automatically when the underlying directory snapshot
    changes (revision-token mismatch).
    """
    return insights_pipeline.build_recommendations(
        engine, tenant_id, force_refresh=refresh,
    )


@router.post("/enrichments/{vendor_id:path}", response_model=VendorDetail)
def enrich_vendor(
    vendor_id: str,
    payload: VendorEnrichmentRequest,
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
) -> VendorDetail:
    """Write a supplier-enrichment overlay for one vendor.

    v1 writes only to ``mart_vendor_enrichments``. It never mutates
    ``mart_vendors`` or Vista ``apvend``.
    """
    try:
        result = service.enrich_vendor(engine, tenant_id, vendor_id, payload)
    except service.VendorEnrichmentStoreMissing as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown vendor: {vendor_id!r}"
        )
    return result


# NOTE: ``/{vendor_id}`` is declared LAST so the literal routes above
# (``/summary``, ``/list``, ``/insights``, ``/recommendations``) aren't
# shadowed by the catch-all.
@router.get("/{vendor_id:path}", response_model=VendorDetail)
def detail(
    vendor_id: str,
    engine: Engine = Depends(get_engine),
    tenant_id: str = Depends(get_tenant_id),
) -> VendorDetail:
    """Detail view for a single vendor."""
    result = service.get_vendor_detail(engine, tenant_id, vendor_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown vendor: {vendor_id!r}"
        )
    return result
