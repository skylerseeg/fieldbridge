"""
Auth endpoints — register tenant + admin user, login, refresh, /me.
POST /auth/register  → creates tenant + first admin user in one step
POST /auth/login     → returns access + refresh tokens
POST /auth/refresh   → exchange refresh token for new access token
GET  /auth/me        → current user + tenant info
POST /auth/logout    → (client-side token discard; placeholder for token blocklist)
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.auth import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    get_current_user, get_current_tenant,
)
from app.models.tenant import Tenant, SubscriptionTier, TenantStatus
from app.models.user import User, UserRole
from app.api.v1.endpoints._azure_verify import (
    AzureVerificationError,
    email_from_claims,
    verify_azure_id_token,
)

router = APIRouter()


# ── Request / Response schemas ────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    company_name: str
    company_slug: str          # URL-safe short name e.g. "acme-civil"
    contact_email: EmailStr
    contact_name: str
    password: str
    tier: SubscriptionTier = SubscriptionTier.STARTER


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    tenant_id: str
    tenant_slug: str
    user_id: str
    role: str


class RefreshRequest(BaseModel):
    refresh_token: str


class AzureCallbackRequest(BaseModel):
    """Azure AD v2 ID token handed back by @azure/msal-browser after a
    successful interactive login. The SPA calls /auth/azure/callback with
    this token; the backend verifies it against the tenant-scoped JWKS and
    swaps it for a FieldBridge access + refresh token pair."""
    id_token: str


class MeResponse(BaseModel):
    user_id: str
    email: str
    full_name: str
    role: str
    tenant_id: str
    tenant_slug: str
    company_name: str
    tier: str
    onboarding_step: int
    vista_connection_verified: bool


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    Create a new tenant + admin user in one step.
    This is the entry point for every new VANCON Technologies customer.
    """
    # Check slug uniqueness
    existing = await db.execute(
        select(Tenant).where(Tenant.slug == req.company_slug)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400,
                            detail=f"Company slug '{req.company_slug}' already taken")

    # Check email uniqueness
    existing_user = await db.execute(
        select(User).where(User.email == req.contact_email)
    )
    if existing_user.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create tenant
    tenant = Tenant(
        slug=req.company_slug,
        company_name=req.company_name,
        contact_email=req.contact_email,
        contact_name=req.contact_name,
        tier=req.tier,
        status=TenantStatus.ONBOARDING,
        onboarding_step=0,
        azure_storage_container=f"fieldbridge-{req.company_slug}",
    )
    db.add(tenant)
    await db.flush()  # get tenant.id before creating user

    # Create first admin user
    user = User(
        tenant_id=tenant.id,
        email=req.contact_email,
        hashed_password=hash_password(req.password),
        full_name=req.contact_name,
        role=UserRole.OWNER,
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await db.refresh(tenant)

    access_token = create_access_token(user.id, tenant.id, user.role)
    refresh_token = create_refresh_token(user.id, tenant.id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        user_id=user.id,
        role=user.role,
    )


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate and return JWT tokens."""
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    # Update last login
    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    result_t = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result_t.scalar_one_or_none()

    access_token = create_access_token(user.id, user.tenant_id, user.role)
    refresh_token = create_refresh_token(user.id, user.tenant_id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        tenant_id=user.tenant_id,
        tenant_slug=tenant.slug if tenant else "",
        user_id=user.id,
        role=user.role,
    )


@router.post("/azure/callback", response_model=TokenResponse)
async def azure_callback(
    req: AzureCallbackRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Exchange an Azure AD v2 ID token for a FieldBridge session.

    Flow:
      1. MSAL in the SPA completes an interactive login against
         `login.microsoftonline.com/{AZURE_TENANT_ID}` and returns an
         `id_token` for audience `AZURE_CLIENT_ID`.
      2. The SPA POSTs that token here.
      3. We verify signature + iss + aud + tid (see _azure_verify).
      4. We look up the matching User by email. Commit 3 does NOT
         auto-provision users — the admin must have seeded/registered the
         account via /auth/register first. That keeps the onboarding flow
         explicit; auto-provisioning lands with the MSP tier when
         user_tenants + auth_identities tables arrive.
      5. We mint FieldBridge JWTs and return them. Session behavior from
         that point on is identical to /auth/login.
    """
    try:
        claims = verify_azure_id_token(req.id_token)
    except AzureVerificationError:
        raise  # already a proper HTTPException
    except Exception as exc:  # pragma: no cover — defensive
        raise AzureVerificationError(f"unexpected: {exc}") from exc

    email = email_from_claims(claims)
    if not email:
        raise AzureVerificationError("no email/upn claim in id_token")

    # Azure UPNs / emails are case-insensitive; users table stores them as
    # entered. Match case-insensitively so "sseegmiller@wedigutah.com" and
    # "SSeegmiller@WeDigUtah.com" both resolve.
    result = await db.execute(
        select(User).where(User.email.ilike(email))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"No FieldBridge account is linked to {email}. "
                "Contact your tenant administrator."
            ),
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    result_t = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result_t.scalar_one_or_none()

    access_token = create_access_token(user.id, user.tenant_id, user.role)
    refresh_tok = create_refresh_token(user.id, user.tenant_id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_tok,
        tenant_id=user.tenant_id,
        tenant_slug=tenant.slug if tenant else "",
        user_id=user.id,
        role=user.role,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a refresh token for a new access token."""
    payload = decode_token(req.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")

    result_t = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result_t.scalar_one_or_none()

    access_token = create_access_token(user.id, user.tenant_id, user.role)
    new_refresh = create_refresh_token(user.id, user.tenant_id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        tenant_id=user.tenant_id,
        tenant_slug=tenant.slug if tenant else "",
        user_id=user.id,
        role=user.role,
    )


@router.get("/me", response_model=MeResponse)
async def me(
    current_user: User = Depends(get_current_user),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Return current user profile + tenant context."""
    return MeResponse(
        user_id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        company_name=tenant.company_name,
        tier=tenant.tier,
        onboarding_step=tenant.onboarding_step,
        vista_connection_verified=tenant.vista_connection_verified,
    )


@router.post("/logout")
async def logout():
    """Client should discard tokens. Placeholder for future token blocklist."""
    return {"message": "Logged out. Discard your tokens client-side."}
