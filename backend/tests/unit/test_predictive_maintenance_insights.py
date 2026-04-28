"""Unit tests for predictive-maintenance Phase-6 recommendation plumbing."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
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
from app.modules.predictive_maintenance import insights as pm_insights
from app.modules.predictive_maintenance.router import (
    _default_engine as pm_default_engine,
    get_engine as pm_get_engine,
    get_tenant_id as pm_get_tenant_id,
    router as pm_router,
)


@pytest.fixture
def empty_engine(tmp_path) -> Engine:
    url = f"sqlite:///{tmp_path / 'predictive_maintenance_recs.db'}"
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


@pytest.fixture
def pm_client(empty_engine, tenant_id) -> TestClient:
    app = FastAPI()
    app.include_router(pm_router, prefix="/api/predictive-maintenance")
    app.dependency_overrides[pm_get_engine] = lambda: empty_engine
    app.dependency_overrides[pm_get_tenant_id] = lambda: tenant_id
    pm_default_engine.cache_clear()
    with TestClient(app) as c:
        yield c


def _fake_response(module: str, revision_token: str) -> InsightResponse:
    return InsightResponse(
        module=module,
        revision_token=revision_token,
        recommendations=[
            Recommendation(
                title="Schedule hydraulic repair on TK149",
                severity=Severity.CRITICAL,
                rationale=(
                    "Synthetic test rationale for predictive maintenance "
                    "long enough to satisfy the Recommendation validator."
                ),
                suggested_action=(
                    "Have the Shop Foreman schedule the hydraulic line "
                    "inspection before the next shift."
                ),
                affected_assets=["TK149"],
            ),
        ],
        input_tokens=42,
        output_tokens=24,
    )


def test_build_data_context_matches_prompt_shape(empty_engine, tenant_id):
    ctx = pm_insights._build_data_context(empty_engine, tenant_id)

    assert set(ctx) == {
        "summary",
        "risk_tier_breakdown",
        "status_breakdown",
        "source_breakdown",
        "failure_mode_breakdown",
        "aging_breakdown",
        "top_equipment_exposure",
        "failure_mode_impact",
        "top_by_exposure",
        "recent_completions",
    }
    assert ctx["summary"]["total_predictions"] == 0
    assert ctx["summary"]["open_overdue_count"] == 0
    assert ctx["status_breakdown"] == {
        "open": 0,
        "acknowledged": 0,
        "scheduled": 0,
        "completed": 0,
        "dismissed": 0,
    }
    assert ctx["aging_breakdown"] == {"fresh": 0, "mature": 0, "stale": 0}
    assert ctx["top_equipment_exposure"] == []
    assert ctx["recent_completions"] == []


def test_build_data_context_is_stable_across_calls(empty_engine, tenant_id):
    """Revision token must be deterministic — no volatile timestamps."""
    ctx_a = pm_insights._build_data_context(empty_engine, tenant_id)
    ctx_b = pm_insights._build_data_context(empty_engine, tenant_id)
    assert llm_module.hash_data_context(ctx_a) == llm_module.hash_data_context(ctx_b)


def test_recommendations_route_cache_miss_writes_row(
    pm_client, monkeypatch, empty_engine, tenant_id,
):
    calls: list[dict[str, Any]] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append({"module": module, "kwargs": kwargs})
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(pm_insights, "generate_insight", _fake_generate)

    r = pm_client.get("/api/predictive-maintenance/recommendations")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["module"] == "predictive_maintenance"
    assert body["recommendations"][0]["affected_assets"] == ["TK149"]
    assert len(calls) == 1
    assert calls[0]["kwargs"]["tenant_id"] == tenant_id

    with sessionmaker(empty_engine)() as s:
        row = s.execute(
            select(LlmInsight).where(
                LlmInsight.tenant_id == tenant_id,
                LlmInsight.module == "predictive_maintenance",
            )
        ).scalar_one_or_none()
    assert row is not None
    assert row.revision_token == body["revision_token"]


def test_recommendations_route_cache_hit_skips_generate(
    pm_client, monkeypatch,
):
    calls: list[Any] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append(1)
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(pm_insights, "generate_insight", _fake_generate)

    first = pm_client.get("/api/predictive-maintenance/recommendations")
    second = pm_client.get("/api/predictive-maintenance/recommendations")
    assert first.status_code == 200
    assert second.status_code == 200
    assert len(calls) == 1
    assert first.json()["revision_token"] == second.json()["revision_token"]


def test_recommendations_route_refresh_forces_regeneration(
    pm_client, monkeypatch,
):
    calls: list[Any] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append(datetime.now(timezone.utc))
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(pm_insights, "generate_insight", _fake_generate)

    pm_client.get("/api/predictive-maintenance/recommendations")
    pm_client.get(
        "/api/predictive-maintenance/recommendations?refresh=true"
    )
    assert len(calls) == 2
