"""
Onboarding wizard — 5-step flow to get a new tenant fully connected.

Step 1: Company profile (auto-completed at registration)
Step 2: Vista SQL credentials + connection test
Step 3: Vista REST API key + test
Step 4: M365 / Azure credentials (email bridge + blob storage)
Step 5: Confirm + activate

GET  /onboarding/status        → current step + completion checklist
POST /onboarding/step/2        → save Vista SQL credentials
POST /onboarding/step/2/test   → test Vista SQL connection live
POST /onboarding/step/3        → save Vista API credentials
POST /onboarding/step/3/test   → test Vista REST API
POST /onboarding/step/4        → save M365 + Azure credentials
POST /onboarding/step/5        → finalize + activate tenant
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.auth import get_current_user, get_current_tenant
from app.core.tenant import test_vista_connection, test_vista_api
from app.models.tenant import Tenant, TenantStatus
from app.models.user import User

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class VistaCredentialsRequest(BaseModel):
    vista_sql_host: str
    vista_sql_port: int = 1433
    vista_sql_db: str
    vista_sql_user: str
    vista_sql_password: str


class VistaApiRequest(BaseModel):
    vista_api_base_url: str
    vista_api_key: str


class M365Request(BaseModel):
    azure_tenant_id: str
    azure_client_id: str
    azure_client_secret: str
    ap_mailbox: str
    azure_storage_connection_string: str = ""


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status")
async def onboarding_status(
    tenant: Tenant = Depends(get_current_tenant),
):
    """Return current onboarding step and a checklist of what's done vs pending."""
    return {
        "current_step": tenant.onboarding_step,
        "company_name": tenant.company_name,
        "checklist": {
            "step_1_company_profile": tenant.onboarding_step >= 1,
            "step_2_vista_sql": bool(tenant.vista_sql_host),
            "step_2_vista_sql_verified": tenant.vista_connection_verified,
            "step_3_vista_api": bool(tenant.vista_api_base_url),
            "step_4_m365": bool(tenant.azure_client_id),
            "step_5_activated": tenant.status == TenantStatus.ACTIVE,
        },
        "is_complete": tenant.status == TenantStatus.ACTIVE,
    }


@router.post("/step/2")
async def save_vista_sql(
    req: VistaCredentialsRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Save Vista SQL Server credentials for this tenant."""
    tenant.vista_sql_host = req.vista_sql_host
    tenant.vista_sql_port = req.vista_sql_port
    tenant.vista_sql_db = req.vista_sql_db
    tenant.vista_sql_user = req.vista_sql_user
    tenant.vista_sql_password = req.vista_sql_password
    tenant.vista_connection_verified = False  # reset — need to re-test
    if tenant.onboarding_step < 2:
        tenant.onboarding_step = 2
    await db.commit()
    return {"saved": True, "next": "POST /onboarding/step/2/test to verify connection"}


@router.post("/step/2/test")
async def test_vista_sql(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Live test the tenant's Vista SQL connection.
    On success, marks vista_connection_verified = True.
    """
    if not tenant.vista_sql_host:
        raise HTTPException(status_code=400,
                            detail="Vista SQL credentials not saved yet. POST /step/2 first.")

    result = test_vista_connection(tenant)

    if result["success"]:
        tenant.vista_connection_verified = True
        # Auto-populate equipment count
        if "active_equipment_count" in result:
            tenant.equipment_unit_count = result["active_equipment_count"]
        await db.commit()

    return result


@router.post("/step/3")
async def save_vista_api(
    req: VistaApiRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Save Vista REST API credentials."""
    tenant.vista_api_base_url = req.vista_api_base_url
    tenant.vista_api_key = req.vista_api_key
    if tenant.onboarding_step < 3:
        tenant.onboarding_step = 3
    await db.commit()
    return {"saved": True, "next": "POST /onboarding/step/3/test to verify"}


@router.post("/step/3/test")
async def test_vista_api_endpoint(
    tenant: Tenant = Depends(get_current_tenant),
):
    """Test the tenant's Vista REST API connection."""
    if not tenant.vista_api_base_url:
        raise HTTPException(status_code=400, detail="Vista API URL not saved yet.")
    return test_vista_api(tenant)


@router.post("/step/4")
async def save_m365(
    req: M365Request,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Save M365 OAuth2 app credentials and Azure storage config."""
    tenant.azure_tenant_id = req.azure_tenant_id
    tenant.azure_client_id = req.azure_client_id
    tenant.azure_client_secret = req.azure_client_secret
    tenant.ap_mailbox = req.ap_mailbox
    if req.azure_storage_connection_string:
        tenant.azure_storage_connection_string = req.azure_storage_connection_string
    if tenant.onboarding_step < 4:
        tenant.onboarding_step = 4
    await db.commit()
    return {"saved": True, "next": "POST /onboarding/step/5 to activate your account"}


@router.post("/step/5")
async def activate_tenant(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Final onboarding step — validate required fields and activate the tenant.
    After this, the tenant can use all FieldBridge features.
    """
    errors = []
    if not tenant.vista_sql_host:
        errors.append("Vista SQL credentials required (Step 2)")
    if not tenant.vista_connection_verified:
        errors.append("Vista SQL connection must be verified (POST /step/2/test)")
    if not tenant.vista_api_base_url:
        errors.append("Vista API credentials required (Step 3)")
    if not tenant.azure_client_id:
        errors.append("M365 credentials required (Step 4)")

    if errors:
        raise HTTPException(status_code=400,
                            detail={"message": "Onboarding incomplete", "errors": errors})

    tenant.status = TenantStatus.ACTIVE
    tenant.onboarding_step = 5
    await db.commit()

    return {
        "activated": True,
        "tenant_slug": tenant.slug,
        "company_name": tenant.company_name,
        "tier": tenant.tier,
        "equipment_units": tenant.equipment_unit_count,
        "monthly_price": tenant.monthly_price,
        "message": (
            f"Welcome to FieldBridge, {tenant.company_name}! "
            f"Your Vista connection is live. Let's start saving money."
        ),
    }
