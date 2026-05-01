"""Unit tests for jobs Phase-6 recommendation plumbing."""
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
from app.modules.jobs import insights as jobs_insights
from app.modules.jobs.router import (
    _default_engine as jobs_default_engine,
    get_engine as jobs_get_engine,
    get_tenant_id as jobs_get_tenant_id,
    router as jobs_router,
)


@pytest.fixture
def empty_engine(tmp_path) -> Engine:
    url = f"sqlite:///{tmp_path / 'jobs_recs.db'}"
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
def jobs_client(empty_engine, tenant_id) -> TestClient:
    app = FastAPI()
    app.include_router(jobs_router, prefix="/api/jobs")
    app.dependency_overrides[jobs_get_engine] = lambda: empty_engine
    app.dependency_overrides[jobs_get_tenant_id] = lambda: tenant_id
    jobs_default_engine.cache_clear()
    with TestClient(app) as c:
        yield c


def _fake_response(module: str, revision_token: str) -> InsightResponse:
    return InsightResponse(
        module=module,
        revision_token=revision_token,
        recommendations=[
            Recommendation(
                title="Review late loss-making jobs",
                severity=Severity.CRITICAL,
                rationale=(
                    "Synthetic test rationale for jobs long enough to "
                    "satisfy the Recommendation validator."
                ),
                suggested_action="Have the CFO review late loss-making jobs.",
                affected_assets=["late"],
            ),
        ],
        input_tokens=42,
        output_tokens=24,
    )


def test_build_data_context_matches_prompt_shape(empty_engine, tenant_id):
    ctx = jobs_insights._build_data_context(empty_engine, tenant_id)

    assert set(ctx) == {
        "summary",
        "at_risk_days",
        "breakeven_band_pct",
        "billing_balance_pct",
        "schedule_breakdown",
        "financial_breakdown",
        "billing_metrics",
        "estimate_accuracy",
        "top_profit",
        "top_loss",
        "top_over_billed",
        "top_under_billed",
    }
    assert ctx["summary"]["total_jobs"] == 0
    assert ctx["at_risk_days"] == 30
    assert ctx["schedule_breakdown"]["late"] == 0
    assert ctx["financial_breakdown"]["loss"] == 0
    assert ctx["billing_metrics"]["total_under_billed"] == 0
    assert ctx["estimate_accuracy"]["samples"] == 0
    assert ctx["top_loss"] == []


def test_recommendations_route_cache_miss_writes_row(
    jobs_client, monkeypatch, empty_engine, tenant_id,
):
    calls: list[dict[str, Any]] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append({"module": module, "kwargs": kwargs})
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(jobs_insights, "generate_insight", _fake_generate)

    r = jobs_client.get("/api/jobs/recommendations")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["module"] == "jobs"
    assert body["recommendations"][0]["affected_assets"] == ["late"]
    assert len(calls) == 1
    assert calls[0]["kwargs"]["tenant_id"] == tenant_id

    with sessionmaker(empty_engine)() as s:
        row = s.execute(
            select(LlmInsight).where(
                LlmInsight.tenant_id == tenant_id,
                LlmInsight.module == "jobs",
            )
        ).scalar_one_or_none()
    assert row is not None
    assert row.revision_token == body["revision_token"]


def test_recommendations_route_cache_hit_skips_generate(
    jobs_client, monkeypatch,
):
    calls: list[Any] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append(1)
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(jobs_insights, "generate_insight", _fake_generate)

    jobs_client.get("/api/jobs/recommendations")
    jobs_client.get("/api/jobs/recommendations")
    assert len(calls) == 1


def test_recommendations_route_refresh_forces_regeneration(
    jobs_client, monkeypatch,
):
    calls: list[Any] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append(datetime.now(timezone.utc))
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(jobs_insights, "generate_insight", _fake_generate)

    jobs_client.get("/api/jobs/recommendations")
    jobs_client.get("/api/jobs/recommendations?refresh=true")
    assert len(calls) == 2
