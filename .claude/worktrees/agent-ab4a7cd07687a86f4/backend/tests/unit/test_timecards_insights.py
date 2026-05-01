"""Unit tests for timecards Phase-6 recommendation plumbing."""
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
from app.modules.timecards import insights as timecards_insights
from app.modules.timecards.router import (
    _default_engine as timecards_default_engine,
    get_engine as timecards_get_engine,
    get_tenant_id as timecards_get_tenant_id,
    router as timecards_router,
)


@pytest.fixture
def empty_engine(tmp_path) -> Engine:
    url = f"sqlite:///{tmp_path / 'timecards_recs.db'}"
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
def timecards_client(empty_engine, tenant_id) -> TestClient:
    app = FastAPI()
    app.include_router(timecards_router, prefix="/api/timecards")
    app.dependency_overrides[timecards_get_engine] = lambda: empty_engine
    app.dependency_overrides[timecards_get_tenant_id] = lambda: tenant_id
    timecards_default_engine.cache_clear()
    with TestClient(app) as c:
        yield c


def _fake_response(module: str, revision_token: str) -> InsightResponse:
    return InsightResponse(
        module=module,
        revision_token=revision_token,
        recommendations=[
            Recommendation(
                title="Reforecast labor classes above plan",
                severity=Severity.WARNING,
                rationale=(
                    "Synthetic test rationale for timecards long enough to "
                    "satisfy the Recommendation validator."
                ),
                suggested_action="Have the Operations Manager review FTE variance.",
                affected_assets=["variance_over"],
            ),
        ],
        input_tokens=42,
        output_tokens=24,
    )


def test_build_data_context_matches_prompt_shape(empty_engine, tenant_id):
    ctx = timecards_insights._build_data_context(empty_engine, tenant_id)

    assert set(ctx) == {
        "summary",
        "variance_band_pct",
        "variance_over",
        "variance_under",
        "overtime_leaders",
        "overhead_ratio",
    }
    assert ctx["summary"]["total_classes"] == 0
    assert ctx["summary"]["total_actual_fte"] == 0
    assert ctx["variance_band_pct"] == 10.0
    assert ctx["variance_over"] == []
    assert ctx["variance_under"] == []
    assert ctx["overtime_leaders"] == []
    assert ctx["overhead_ratio"] == {
        "overhead_fte": 0.0,
        "direct_fte": 0,
        "ratio_pct": None,
    }


def test_recommendations_route_cache_miss_writes_row(
    timecards_client, monkeypatch, empty_engine, tenant_id,
):
    calls: list[dict[str, Any]] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append({"module": module, "kwargs": kwargs})
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(timecards_insights, "generate_insight", _fake_generate)

    r = timecards_client.get("/api/timecards/recommendations")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["module"] == "timecards"
    assert body["recommendations"][0]["affected_assets"] == ["variance_over"]
    assert len(calls) == 1
    assert calls[0]["kwargs"]["tenant_id"] == tenant_id

    with sessionmaker(empty_engine)() as s:
        row = s.execute(
            select(LlmInsight).where(
                LlmInsight.tenant_id == tenant_id,
                LlmInsight.module == "timecards",
            )
        ).scalar_one_or_none()
    assert row is not None
    assert row.revision_token == body["revision_token"]


def test_recommendations_route_cache_hit_skips_generate(
    timecards_client, monkeypatch,
):
    calls: list[Any] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append(1)
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(timecards_insights, "generate_insight", _fake_generate)

    timecards_client.get("/api/timecards/recommendations")
    timecards_client.get("/api/timecards/recommendations")
    assert len(calls) == 1


def test_recommendations_route_refresh_forces_regeneration(
    timecards_client, monkeypatch,
):
    calls: list[Any] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append(datetime.now(timezone.utc))
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(timecards_insights, "generate_insight", _fake_generate)

    timecards_client.get("/api/timecards/recommendations")
    timecards_client.get("/api/timecards/recommendations?refresh=true")
    assert len(calls) == 2
