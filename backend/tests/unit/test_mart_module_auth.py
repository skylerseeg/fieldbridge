"""Auth coverage for mart-backed module dependencies."""
from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.auth import get_current_tenant
from app.modules.dependencies import get_tenant_id
from app.modules.equipment.router import router as equipment_router


def test_mart_routes_require_authentication():
    app = FastAPI()
    app.include_router(equipment_router, prefix="/api/equipment")

    with TestClient(app) as client:
        response = client.get("/api/equipment/summary")

    assert response.status_code == 401


def test_get_tenant_id_uses_authenticated_tenant():
    class CurrentTenant:
        id = "authenticated-tenant-id"

    app = FastAPI()
    app.get("/tenant-id")(lambda tenant_id=Depends(get_tenant_id): {"tenant_id": tenant_id})
    app.dependency_overrides[get_current_tenant] = lambda: CurrentTenant()

    with TestClient(app) as client:
        response = client.get("/tenant-id")

    assert response.status_code == 200
    assert response.json() == {"tenant_id": "authenticated-tenant-id"}
