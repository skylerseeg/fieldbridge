"""Integration tests for the vendors supplier-enrichment write/read path."""
from __future__ import annotations

import hashlib
import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import sessionmaker

import app.services.excel_marts  # noqa: F401
from app.core.database import Base
from app.models.tenant import SubscriptionTier, Tenant, TenantStatus
from app.modules.vendors.router import (
    _default_engine,
    get_engine,
    get_tenant_id,
    router as vendors_router,
)

def _row_hash_for(row: dict) -> str:
    payload = json.dumps(row, sort_keys=True, default=str)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


@pytest.fixture
def seeded_engine(tmp_path) -> Engine:
    engine = create_engine(f"sqlite:///{tmp_path / 'vendors_it.db'}", future=True)
    Base.metadata.create_all(engine)
    tenant_id = str(uuid.uuid4())

    with sessionmaker(engine)() as s:
        s.add(
            Tenant(
                id=tenant_id,
                slug="vancon",
                company_name="VanCon Inc.",
                contact_email="admin@vancon.test",
                tier=SubscriptionTier.INTERNAL,
                status=TenantStatus.ACTIVE,
            )
        )
        s.commit()

    with engine.begin() as conn:
        row = {
            "name": "Precision Surveyors",
            "firm_type": "Service",
            "contact": None,
            "title": None,
            "email": None,
            "phone": None,
            "code_1": None,
            "code_2": None,
            "code_3": None,
            "code_4": None,
            "code_5": None,
        }
        conn.execute(
            text(
                """
                INSERT INTO mart_vendors
                    (tenant_id, _row_hash, name, firm_type, contact, title,
                     email, phone, code_1, code_2, code_3, code_4, code_5)
                VALUES
                    (:tenant_id, :_row_hash, :name, :firm_type, :contact,
                     :title, :email, :phone, :code_1, :code_2, :code_3,
                     :code_4, :code_5)
                """
            ),
            {"tenant_id": tenant_id, "_row_hash": _row_hash_for(row), **row},
        )

    return engine


@pytest.fixture
def seeded_tenant_id(seeded_engine: Engine) -> str:
    with sessionmaker(seeded_engine)() as s:
        return s.execute(text("SELECT id FROM tenants WHERE slug = 'vancon'")).scalar_one()


@pytest.fixture
def client(seeded_engine: Engine, seeded_tenant_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(vendors_router, prefix="/api/vendors")
    app.dependency_overrides[get_engine] = lambda: seeded_engine
    app.dependency_overrides[get_tenant_id] = lambda: seeded_tenant_id
    _default_engine.cache_clear()

    with TestClient(app) as c:
        yield c


def test_enrichment_persists_and_reads_back_through_public_api(client: TestClient):
    write = client.post(
        "/api/vendors/enrichments/Precision Surveyors",
        json={
            "contact": "Paula Planner",
            "email": "paula@precision.test",
            "phone": "555-0199",
            "firm_type": "supplier",
            "codes": ["3100-Earthwork"],
        },
    )
    assert write.status_code == 200, write.text
    assert write.json()["contact_status"] == "complete"

    detail = client.get("/api/vendors/Precision Surveyors")
    assert detail.status_code == 200
    assert detail.json()["enriched"] is True
    assert detail.json()["firm_type"] == "supplier"

    listing = client.get("/api/vendors/list?contact_status=complete")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["coding_status"] == "coded"
