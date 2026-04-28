"""Unit tests for bids Phase-6 recommendation plumbing."""
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
from app.modules.bids import insights as bids_insights
from app.modules.bids.router import (
    _default_engine as bids_default_engine,
    get_engine as bids_get_engine,
    get_tenant_id as bids_get_tenant_id,
    router as bids_router,
)


@pytest.fixture
def empty_engine(tmp_path) -> Engine:
    url = f"sqlite:///{tmp_path / 'bids_recs.db'}"
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
def bids_client(empty_engine, tenant_id) -> TestClient:
    app = FastAPI()
    app.include_router(bids_router, prefix="/api/bids")
    app.dependency_overrides[bids_get_engine] = lambda: empty_engine
    app.dependency_overrides[bids_get_tenant_id] = lambda: tenant_id
    bids_default_engine.cache_clear()
    with TestClient(app) as c:
        yield c


def _fake_response(module: str, revision_token: str) -> InsightResponse:
    return InsightResponse(
        module=module,
        revision_token=revision_token,
        recommendations=[
            Recommendation(
                title="Review wide-loss bid cohort",
                severity=Severity.CRITICAL,
                rationale=(
                    "Synthetic test rationale for bids long enough to "
                    "satisfy the Recommendation validator."
                ),
                suggested_action="Have the Chief Estimator review wide losses.",
                affected_assets=["wide"],
            ),
        ],
        input_tokens=42,
        output_tokens=24,
    )


def test_build_data_context_matches_prompt_shape(empty_engine, tenant_id):
    ctx = bids_insights._build_data_context(empty_engine, tenant_id)

    assert set(ctx) == {
        "summary",
        "close_max",
        "moderate_max",
        "light_max",
        "typical_max",
        "outcome_breakdown",
        "margin_tier_breakdown",
        "competition_tier_breakdown",
        "win_rate_by_bid_type",
        "win_rate_by_estimator",
        "win_rate_by_county",
        "near_misses",
        "big_wins",
        "risk_flag_frequency",
    }
    assert ctx["summary"]["total_bids"] == 0
    assert ctx["summary"]["win_rate"] == 0
    assert ctx["moderate_max"] == 0.10
    assert ctx["outcome_breakdown"]["lost"] == 0
    assert ctx["margin_tier_breakdown"]["wide"] == 0
    assert ctx["competition_tier_breakdown"]["crowded"] == 0
    assert ctx["near_misses"] == []
    assert len(ctx["risk_flag_frequency"]) == 8


def test_recommendations_route_cache_miss_writes_row(
    bids_client, monkeypatch, empty_engine, tenant_id,
):
    calls: list[dict[str, Any]] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append({"module": module, "kwargs": kwargs})
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(bids_insights, "generate_insight", _fake_generate)

    r = bids_client.get("/api/bids/recommendations")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["module"] == "bids"
    assert body["recommendations"][0]["affected_assets"] == ["wide"]
    assert len(calls) == 1
    assert calls[0]["kwargs"]["tenant_id"] == tenant_id

    with sessionmaker(empty_engine)() as s:
        row = s.execute(
            select(LlmInsight).where(
                LlmInsight.tenant_id == tenant_id,
                LlmInsight.module == "bids",
            )
        ).scalar_one_or_none()
    assert row is not None
    assert row.revision_token == body["revision_token"]


def test_recommendations_route_cache_hit_skips_generate(
    bids_client, monkeypatch,
):
    calls: list[Any] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append(1)
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(bids_insights, "generate_insight", _fake_generate)

    bids_client.get("/api/bids/recommendations")
    bids_client.get("/api/bids/recommendations")
    assert len(calls) == 1


def test_recommendations_route_refresh_forces_regeneration(
    bids_client, monkeypatch,
):
    calls: list[Any] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append(datetime.now(timezone.utc))
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(bids_insights, "generate_insight", _fake_generate)

    bids_client.get("/api/bids/recommendations")
    bids_client.get("/api/bids/recommendations?refresh=true")
    assert len(calls) == 2
