"""Unit tests for proposals Phase-6 recommendation plumbing."""
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
from app.modules.proposals import insights as proposals_insights
from app.modules.proposals.router import (
    _default_engine as proposals_default_engine,
    get_engine as proposals_get_engine,
    get_tenant_id as proposals_get_tenant_id,
    router as proposals_router,
)


@pytest.fixture
def empty_engine(tmp_path) -> Engine:
    url = f"sqlite:///{tmp_path / 'proposals_recs.db'}"
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
def proposals_client(empty_engine, tenant_id) -> TestClient:
    app = FastAPI()
    app.include_router(proposals_router, prefix="/api/proposals")
    app.dependency_overrides[proposals_get_engine] = lambda: empty_engine
    app.dependency_overrides[proposals_get_tenant_id] = lambda: tenant_id
    proposals_default_engine.cache_clear()
    with TestClient(app) as c:
        yield c


def _fake_response(module: str, revision_token: str) -> InsightResponse:
    return InsightResponse(
        module=module,
        revision_token=revision_token,
        recommendations=[
            Recommendation(
                title="Review proposal geography mix",
                severity=Severity.WARNING,
                rationale=(
                    "Synthetic test rationale for proposals long enough to "
                    "satisfy the Recommendation validator."
                ),
                suggested_action="Have the Proposal Manager review geography mix.",
                affected_assets=["out_of_state"],
            ),
        ],
        input_tokens=42,
        output_tokens=24,
    )


def test_build_data_context_matches_prompt_shape(empty_engine, tenant_id):
    ctx = proposals_insights._build_data_context(empty_engine, tenant_id)

    assert set(ctx) == {
        "summary",
        "primary_state",
        "bid_type_category_breakdown",
        "geography_tier_breakdown",
        "top_owners",
        "top_bid_types",
        "top_counties",
        "top_states",
        "competitor_frequency",
        "fee_statistics",
    }
    assert ctx["summary"]["total_proposals"] == 0
    assert ctx["primary_state"] == "UT"
    assert ctx["bid_type_category_breakdown"]["other"] == 0
    assert ctx["geography_tier_breakdown"]["out_of_state"] == 0
    assert ctx["top_owners"] == []
    assert ctx["competitor_frequency"] == []
    assert len(ctx["fee_statistics"]) == 10


def test_recommendations_route_cache_miss_writes_row(
    proposals_client, monkeypatch, empty_engine, tenant_id,
):
    calls: list[dict[str, Any]] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append({"module": module, "kwargs": kwargs})
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(proposals_insights, "generate_insight", _fake_generate)

    r = proposals_client.get("/api/proposals/recommendations")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["module"] == "proposals"
    assert body["recommendations"][0]["affected_assets"] == ["out_of_state"]
    assert len(calls) == 1
    assert calls[0]["kwargs"]["tenant_id"] == tenant_id

    with sessionmaker(empty_engine)() as s:
        row = s.execute(
            select(LlmInsight).where(
                LlmInsight.tenant_id == tenant_id,
                LlmInsight.module == "proposals",
            )
        ).scalar_one_or_none()
    assert row is not None
    assert row.revision_token == body["revision_token"]


def test_recommendations_route_cache_hit_skips_generate(
    proposals_client, monkeypatch,
):
    calls: list[Any] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append(1)
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(proposals_insights, "generate_insight", _fake_generate)

    proposals_client.get("/api/proposals/recommendations")
    proposals_client.get("/api/proposals/recommendations")
    assert len(calls) == 1


def test_recommendations_route_refresh_forces_regeneration(
    proposals_client, monkeypatch,
):
    calls: list[Any] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append(datetime.now(timezone.utc))
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(proposals_insights, "generate_insight", _fake_generate)

    proposals_client.get("/api/proposals/recommendations")
    proposals_client.get("/api/proposals/recommendations?refresh=true")
    assert len(calls) == 2
