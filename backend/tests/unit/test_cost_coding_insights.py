"""Unit tests for cost-coding Phase-6 recommendation plumbing."""
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
from app.modules.cost_coding import insights as cost_coding_insights
from app.modules.cost_coding.router import (
    _default_engine as cost_coding_default_engine,
    get_engine as cost_coding_get_engine,
    get_tenant_id as cost_coding_get_tenant_id,
    router as cost_coding_router,
)


@pytest.fixture
def empty_engine(tmp_path) -> Engine:
    url = f"sqlite:///{tmp_path / 'cost_coding_recs.db'}"
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
def cost_coding_client(empty_engine, tenant_id) -> TestClient:
    app = FastAPI()
    app.include_router(cost_coding_router, prefix="/api/cost-coding")
    app.dependency_overrides[cost_coding_get_engine] = lambda: empty_engine
    app.dependency_overrides[cost_coding_get_tenant_id] = lambda: tenant_id
    cost_coding_default_engine.cache_clear()
    with TestClient(app) as c:
        yield c


def _fake_response(module: str, revision_token: str) -> InsightResponse:
    return InsightResponse(
        module=module,
        revision_token=revision_token,
        recommendations=[
            Recommendation(
                title="Clean up zero-cost activity codes",
                severity=Severity.INFO,
                rationale=(
                    "Synthetic test rationale for cost coding long enough "
                    "to satisfy the Recommendation validator."
                ),
                suggested_action="Have the Cost Engineer review uncosted codes.",
                affected_assets=["zero"],
            ),
        ],
        input_tokens=42,
        output_tokens=24,
    )


def test_build_data_context_matches_prompt_shape(empty_engine, tenant_id):
    ctx = cost_coding_insights._build_data_context(empty_engine, tenant_id)

    assert set(ctx) == {
        "summary",
        "category_breakdown",
        "size_tier_breakdown",
        "usage_tier_breakdown",
        "category_mix",
        "top_by_cost",
        "top_by_usage",
        "top_by_hours",
        "top_major_codes",
        "uncosted_codes",
    }
    assert ctx["summary"]["total_codes"] == 0
    assert ctx["summary"]["total_direct_cost"] == 0
    assert ctx["category_breakdown"]["zero"] == 0
    assert ctx["size_tier_breakdown"]["major"] == 0
    assert ctx["usage_tier_breakdown"]["singleton"] == 0
    assert ctx["top_by_cost"] == []
    assert ctx["uncosted_codes"] == []


def test_recommendations_route_cache_miss_writes_row(
    cost_coding_client, monkeypatch, empty_engine, tenant_id,
):
    calls: list[dict[str, Any]] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append({"module": module, "kwargs": kwargs})
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(cost_coding_insights, "generate_insight", _fake_generate)

    r = cost_coding_client.get("/api/cost-coding/recommendations")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["module"] == "cost_coding"
    assert body["recommendations"][0]["affected_assets"] == ["zero"]
    assert len(calls) == 1
    assert calls[0]["kwargs"]["tenant_id"] == tenant_id

    with sessionmaker(empty_engine)() as s:
        row = s.execute(
            select(LlmInsight).where(
                LlmInsight.tenant_id == tenant_id,
                LlmInsight.module == "cost_coding",
            )
        ).scalar_one_or_none()
    assert row is not None
    assert row.revision_token == body["revision_token"]


def test_recommendations_route_cache_hit_skips_generate(
    cost_coding_client, monkeypatch,
):
    calls: list[Any] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append(1)
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(cost_coding_insights, "generate_insight", _fake_generate)

    cost_coding_client.get("/api/cost-coding/recommendations")
    cost_coding_client.get("/api/cost-coding/recommendations")
    assert len(calls) == 1


def test_recommendations_route_refresh_forces_regeneration(
    cost_coding_client, monkeypatch,
):
    calls: list[Any] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append(datetime.now(timezone.utc))
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(cost_coding_insights, "generate_insight", _fake_generate)

    cost_coding_client.get("/api/cost-coding/recommendations")
    cost_coding_client.get("/api/cost-coding/recommendations?refresh=true")
    assert len(calls) == 2
