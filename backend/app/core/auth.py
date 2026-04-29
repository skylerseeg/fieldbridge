"""
Auth core — JWT token creation/validation, password hashing, FastAPI dependencies.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import bcrypt
import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.core.database import get_db

bearer_scheme = HTTPBearer()

ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8   # 8 hours
REFRESH_TOKEN_EXPIRE_DAYS = 30


# ── Password ──────────────────────────────────────────────────────────────────
#
# Direct bcrypt — no passlib wrapper. passlib 1.7.4 (last release 2020) runs a
# startup probe that feeds a >72-byte test string to bcrypt.hashpw; bcrypt 4+
# enforces the 72-byte limit strictly and crashes passlib's init. passlib has
# been in maintenance-only mode since 2020 with no fix on the horizon, so we
# call bcrypt directly. Hash format on disk is unchanged ($2b$...) so any
# prior passlib-hashed values still verify against bcrypt.checkpw.

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash on disk — treat as auth failure rather than 500.
        return False


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(user_id: str, tenant_id: str, role: str,
                        expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def create_refresh_token(user_id: str, tenant_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid token")


# ── FastAPI Dependencies ──────────────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Inject authenticated User into route handlers."""
    from app.models.user import User
    payload = decode_token(credentials.credentials)
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


async def get_current_tenant(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Inject the Tenant object for the authenticated user."""
    from app.models.tenant import Tenant
    result = await db.execute(
        select(Tenant).where(Tenant.id == current_user.tenant_id)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


def require_role(*roles: str):
    """Dependency factory: restrict endpoint to specific roles."""
    async def _check(current_user=Depends(get_current_user)):
        if current_user.role not in roles and current_user.role != "fieldbridge_admin":
            raise HTTPException(status_code=403,
                                detail=f"Role '{current_user.role}' not permitted. "
                                       f"Required: {list(roles)}")
        return current_user
    return _check


def require_admin():
    """Restrict to VANCON Technologies internal admins."""
    return require_role("fieldbridge_admin")
