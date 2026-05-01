"""
Admin endpoints — VANCON Technologies internal use only.
Requires fieldbridge_admin role.

GET  /admin/tenants              → list all tenants + status
GET  /admin/tenants/{slug}       → single tenant detail
PATCH /admin/tenants/{slug}      → update tier / status
GET  /admin/usage                → cross-tenant usage this month
GET  /admin/usage/{tenant_slug}  → single-tenant usage detail
GET  /admin/health               → platform health summary
"""
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.auth import require_role
from app.models.tenant import Tenant, SubscriptionTier, TenantStatus
from app.models.user import UserRole
from app.services.metering import get_all_tenants_usage, get_tenant_usage_summary

router = APIRouter()

_admin_only = Depends(require_role(UserRole.FIELDBRIDGE_ADMIN))


class TenantUpdateRequest(BaseModel):
    tier: Optional[SubscriptionTier] = None
    status: Optional[TenantStatus] = None
    equipment_unit_count: Optional[int] = None


@router.get("/tenants")
async def list_tenants(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _=_admin_only,
):
    """List all tenants with key metrics."""
    query = select(Tenant)
    if status:
        try:
            query = query.where(Tenant.status == TenantStatus(status))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    result = await db.execute(query.order_by(Tenant.created_at.desc()))
    tenants = result.scalars().all()

    return [
        {
            "id": t.id,
            "slug": t.slug,
            "company_name": t.company_name,
            "contact_email": t.contact_email,
            "tier": t.tier,
            "status": t.status,
            "equipment_units": t.equipment_unit_count,
            "monthly_price": t.monthly_price,
            "onboarding_step": t.onboarding_step,
            "vista_verified": t.vista_connection_verified,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in tenants
    ]


@router.get("/tenants/{slug}")
async def get_tenant_detail(
    slug: str,
    db: AsyncSession = Depends(get_db),
    _=_admin_only,
):
    """Full tenant detail (credentials redacted)."""
    result = await db.execute(select(Tenant).where(Tenant.slug == slug))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return {
        "id": tenant.id,
        "slug": tenant.slug,
        "company_name": tenant.company_name,
        "contact_email": tenant.contact_email,
        "contact_name": tenant.contact_name,
        "tier": tenant.tier,
        "status": tenant.status,
        "equipment_units": tenant.equipment_unit_count,
        "monthly_price": tenant.monthly_price,
        "onboarding_step": tenant.onboarding_step,
        "vista_sql_host": tenant.vista_sql_host,
        "vista_sql_db": tenant.vista_sql_db,
        "vista_connection_verified": tenant.vista_connection_verified,
        "vista_api_configured": bool(tenant.vista_api_base_url),
        "m365_configured": bool(tenant.azure_client_id),
        "blob_container": tenant.azure_storage_container,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
    }


@router.patch("/tenants/{slug}")
async def update_tenant(
    slug: str,
    req: TenantUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _=_admin_only,
):
    """Update a tenant's tier, status, or equipment count."""
    result = await db.execute(select(Tenant).where(Tenant.slug == slug))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if req.tier is not None:
        tenant.tier = req.tier
    if req.status is not None:
        tenant.status = req.status
    if req.equipment_unit_count is not None:
        tenant.equipment_unit_count = req.equipment_unit_count

    await db.commit()
    return {"updated": True, "slug": slug, "tier": tenant.tier,
            "status": tenant.status, "monthly_price": tenant.monthly_price}


@router.get("/usage")
async def platform_usage(
    month: Optional[str] = Query(default=None,
                                  description="YYYY-MM format, defaults to current month"),
    db: AsyncSession = Depends(get_db),
    _=_admin_only,
):
    """Cross-tenant Claude API usage for a month. Shows cost attribution per tenant."""
    month_date = _parse_month(month)
    usage = await get_all_tenants_usage(db, month_date)

    total_cost = sum(u["total_cost_usd"] for u in usage)
    total_calls = sum(u["total_calls"] for u in usage)

    return {
        "month": month_date.strftime("%Y-%m"),
        "platform_total_cost_usd": round(total_cost, 4),
        "platform_total_calls": total_calls,
        "by_tenant": usage,
    }


@router.get("/usage/{tenant_slug}")
async def tenant_usage(
    tenant_slug: str,
    month: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _=_admin_only,
):
    """Detailed usage breakdown for a single tenant by agent."""
    result = await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    month_date = _parse_month(month)
    return await get_tenant_usage_summary(db, tenant.id, month_date)


@router.get("/health")
async def platform_health(
    db: AsyncSession = Depends(get_db),
    _=_admin_only,
):
    """Platform health — tenant counts, active users, onboarding funnel."""
    all_tenants = (await db.execute(select(Tenant))).scalars().all()

    by_status = {}
    by_tier = {}
    for t in all_tenants:
        by_status[t.status] = by_status.get(t.status, 0) + 1
        by_tier[t.tier] = by_tier.get(t.tier, 0) + 1

    active_count = by_status.get(TenantStatus.ACTIVE, 0)
    mrr = sum(t.monthly_price for t in all_tenants
              if t.status == TenantStatus.ACTIVE)

    return {
        "total_tenants": len(all_tenants),
        "active_tenants": active_count,
        "by_status": {k: v for k, v in by_status.items()},
        "by_tier": {k: v for k, v in by_tier.items()},
        "mrr_usd": mrr,
        "arr_usd": mrr * 12,
    }


def _parse_month(month_str: Optional[str]) -> date:
    if not month_str:
        return date.today().replace(day=1)
    try:
        parts = month_str.split("-")
        return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, IndexError):
        raise HTTPException(status_code=400,
                            detail="Invalid month format. Use YYYY-MM")
