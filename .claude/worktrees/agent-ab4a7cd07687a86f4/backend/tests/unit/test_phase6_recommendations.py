"""Phase-6 ``/recommendations`` endpoint smoke tests.

Covers both ``equipment`` and ``vendors`` modules. We monkeypatch
``app.core.llm.generate_insight`` to return canned responses so the
test never touches the Anthropic SDK or the network.

What we lock in:
  * Cache miss -> generate_insight invoked + row written.
  * Cache hit  -> generate_insight NOT invoked.
  * Stale cache (mismatched revision_token) -> regenerated.
  * ``?refresh=true`` -> regenerated even when fresh.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import sessionmaker

# Register every mart Table on Base.metadata.
import app.services.excel_marts  # noqa: F401
from app.core.database import Base
from app.core import llm as llm_module
from app.core.llm import InsightResponse, Recommendation, Severity
from app.models.llm_insight import LlmInsight
from app.models.tenant import SubscriptionTier, Tenant, TenantStatus
from app.modules.equipment import insights as equipment_insights
from app.modules.equipment.router import (
    _default_engine as equipment_default_engine,
    get_engine as equipment_get_engine,
    get_tenant_id as equipment_get_tenant_id,
    router as equipment_router,
)
from app.modules.vendors import insights as vendors_insights
from app.modules.vendors.router import (
    _default_engine as vendors_default_engine,
    get_engine as vendors_get_engine,
    get_tenant_id as vendors_get_tenant_id,
    router as vendors_router,
)


# --------------------------------------------------------------------------- #
# Shared fixtures                                                             #
# --------------------------------------------------------------------------- #


@pytest.fixture
def empty_engine(tmp_path) -> Engine:
    """Mart-schema-complete SQLite — no rows. Service layer returns
    well-formed empty payloads, which is fine for these tests since
    we mock the LLM call anyway."""
    url = f"sqlite:///{tmp_path / 'phase6_test.db'}"
    engine = create_engine(url, future=True)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def tenant_id(empty_engine: Engine) -> str:
    tid = str(uuid.uuid4())
    with sessionmaker(empty_engine)() as s:
        s.add(
            Tenant(
                id=tid,
                slug="vancon",
                company_name="VanCon Inc.",
                contact_email="admin@vancon.test",
                tier=SubscriptionTier.INTERNAL,
                status=TenantStatus.ACTIVE,
            )
        )
        s.commit()
    return tid


def _fake_response(module: str, revision_token: str) -> InsightResponse:
    return InsightResponse(
        module=module,
        revision_token=revision_token,
        recommendations=[
            Recommendation(
                title=f"Investigate {module} cohort",
                severity=Severity.WARNING,
                rationale=(
                    f"Synthetic test rationale for {module} long enough to "
                    f"pass the min_length validator on Recommendation."
                ),
                suggested_action="Have the Operations Manager review the data.",
                affected_assets=[],
            ),
        ],
        input_tokens=42,
        output_tokens=24,
    )


# --------------------------------------------------------------------------- #
# Equipment                                                                   #
# --------------------------------------------------------------------------- #


@pytest.fixture
def equipment_client(empty_engine, tenant_id) -> TestClient:
    app = FastAPI()
    app.include_router(equipment_router, prefix="/api/equipment")
    app.dependency_overrides[equipment_get_engine] = lambda: empty_engine
    app.dependency_overrides[equipment_get_tenant_id] = lambda: tenant_id
    equipment_default_engine.cache_clear()
    with TestClient(app) as c:
        yield c


class TestEquipmentRecommendations:
    def test_cache_miss_calls_generate_insight(
        self, equipment_client, monkeypatch, empty_engine, tenant_id,
    ):
        calls: list[dict[str, Any]] = []

        def _fake_generate(module, ctx, prompt, **kwargs):
            calls.append({"module": module, "kwargs": kwargs})
            return _fake_response(module, llm_module.hash_data_context(ctx))

        # Patch on the equipment_insights module — that's the binding
        # the route handler resolves through.
        monkeypatch.setattr(equipment_insights, "generate_insight", _fake_generate)

        r = equipment_client.get("/api/equipment/recommendations")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["module"] == "equipment"
        assert body["recommendations"][0]["title"].startswith("Investigate equipment")
        assert len(calls) == 1

        # Cache row was written.
        with sessionmaker(empty_engine)() as s:
            row = s.execute(
                select(LlmInsight).where(
                    LlmInsight.tenant_id == tenant_id,
                    LlmInsight.module == "equipment",
                )
            ).scalar_one_or_none()
        assert row is not None
        assert row.revision_token == body["revision_token"]

    def test_cache_hit_skips_generate_insight(
        self, equipment_client, monkeypatch,
    ):
        calls: list[Any] = []

        def _fake_generate(module, ctx, prompt, **kwargs):
            calls.append(1)
            return _fake_response(module, llm_module.hash_data_context(ctx))

        monkeypatch.setattr(equipment_insights, "generate_insight", _fake_generate)

        first = equipment_client.get("/api/equipment/recommendations")
        second = equipment_client.get("/api/equipment/recommendations")
        assert first.status_code == 200
        assert second.status_code == 200
        assert len(calls) == 1  # second call hit the cache
        assert first.json()["revision_token"] == second.json()["revision_token"]

    def test_refresh_query_param_forces_regeneration(
        self, equipment_client, monkeypatch,
    ):
        calls: list[Any] = []

        def _fake_generate(module, ctx, prompt, **kwargs):
            calls.append(1)
            return _fake_response(module, llm_module.hash_data_context(ctx))

        monkeypatch.setattr(equipment_insights, "generate_insight", _fake_generate)

        equipment_client.get("/api/equipment/recommendations")
        equipment_client.get("/api/equipment/recommendations?refresh=true")
        assert len(calls) == 2

    def test_stale_cache_regenerates(
        self, equipment_client, monkeypatch, empty_engine, tenant_id,
    ):
        # Pre-seed a cache row with an obviously bogus revision_token.
        with sessionmaker(empty_engine)() as s:
            s.add(
                LlmInsight(
                    tenant_id=tenant_id,
                    module="equipment",
                    revision_token="stale-stale-stale",
                    payload_json=_fake_response(
                        "equipment", "stale-stale-stale",
                    ).model_dump_json(),
                    input_tokens=0,
                    output_tokens=0,
                    model="claude-opus-4-7",
                    created_at=datetime.now(timezone.utc),
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=6),
                )
            )
            s.commit()

        calls: list[Any] = []

        def _fake_generate(module, ctx, prompt, **kwargs):
            calls.append(1)
            return _fake_response(module, llm_module.hash_data_context(ctx))

        monkeypatch.setattr(equipment_insights, "generate_insight", _fake_generate)

        r = equipment_client.get("/api/equipment/recommendations")
        assert r.status_code == 200
        # Stale revision_token forced regeneration.
        assert len(calls) == 1
        assert r.json()["revision_token"] != "stale-stale-stale"


# --------------------------------------------------------------------------- #
# Vendors                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def vendors_client(empty_engine, tenant_id) -> TestClient:
    app = FastAPI()
    app.include_router(vendors_router, prefix="/api/vendors")
    app.dependency_overrides[vendors_get_engine] = lambda: empty_engine
    app.dependency_overrides[vendors_get_tenant_id] = lambda: tenant_id
    vendors_default_engine.cache_clear()
    with TestClient(app) as c:
        yield c


class TestVendorsRecommendations:
    def test_cache_miss_calls_generate_insight(
        self, vendors_client, monkeypatch, empty_engine, tenant_id,
    ):
        calls: list[Any] = []

        def _fake_generate(module, ctx, prompt, **kwargs):
            calls.append(1)
            return _fake_response(module, llm_module.hash_data_context(ctx))

        monkeypatch.setattr(vendors_insights, "generate_insight", _fake_generate)

        r = vendors_client.get("/api/vendors/recommendations")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["module"] == "vendors"
        assert len(calls) == 1

        with sessionmaker(empty_engine)() as s:
            row = s.execute(
                select(LlmInsight).where(
                    LlmInsight.tenant_id == tenant_id,
                    LlmInsight.module == "vendors",
                )
            ).scalar_one_or_none()
        assert row is not None

    def test_cache_hit_skips_generate_insight(
        self, vendors_client, monkeypatch,
    ):
        calls: list[Any] = []

        def _fake_generate(module, ctx, prompt, **kwargs):
            calls.append(1)
            return _fake_response(module, llm_module.hash_data_context(ctx))

        monkeypatch.setattr(vendors_insights, "generate_insight", _fake_generate)
        vendors_client.get("/api/vendors/recommendations")
        vendors_client.get("/api/vendors/recommendations")
        assert len(calls) == 1
