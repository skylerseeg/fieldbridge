"""Shared FastAPI dependencies for mart-backed modules."""
from __future__ import annotations

from fastapi import Depends

from app.core.auth import get_current_tenant
from app.models.tenant import Tenant


def get_tenant_id(tenant: Tenant = Depends(get_current_tenant)) -> str:
    """Return the authenticated tenant id for mart queries."""
    return tenant.id
