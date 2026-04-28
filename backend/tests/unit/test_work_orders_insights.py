"""Unit tests for work-order Phase-6 recommendation plumbing."""
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
from app.modules.work_orders import insights as work_orders_insights
from app.modules.work_orders.router import (
    _default_engine as work_orders_default_engine,
    get_engine as work_orders_get_engine,
    get_tenant_id as work_orders_get_tenant_id,
    router as work_orders_router,
)


@pytest.fixture
def empty_engine(tmp_path) -> Engine:
    url = f"sqlite:///{tmp_path / 'work_orders_recs.db'}"
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
def work_orders_client(empty_engine, tenant_id) -> TestClient:
    app = FastAPI()
    app.include_router(work_orders_router, prefix="/api/work-orders")
    app.dependency_overrides[work_orders_get_engine] = lambda: empty_engine
    app.dependency_overrides[work_orders_get_tenant_id] = lambda: tenant_id
    work_orders_default_engine.cache_clear()
    with TestClient(app) as c:
        yield c


def _fake_response(module: str, revision_token: str) -> InsightResponse:
    return InsightResponse(
        module=module,
        revision_token=revision_token,
        recommendations=[
            Recommendation(
                title="Review overdue work-order backlog",
                severity=Severity.WARNING,
                rationale=(
                    "Synthetic test rationale for work orders long enough "
                    "to satisfy the Recommendation validator."
                ),
                suggested_action="Have the Shop Manager review the backlog.",
                affected_assets=["overdue"],
            ),
        ],
        input_tokens=42,
        output_tokens=24,
    )


def test_build_data_context_matches_prompt_shape(empty_engine, tenant_id):
    ctx = work_orders_insights._build_data_context(empty_engine, tenant_id)

    assert set(ctx) == {
        "summary",
        "overdue_threshold_days",
        "status_counts",
        "avg_age_days_open",
        "overdue_count",
        "cost_vs_budget",
    }
    assert ctx["summary"]["total_work_orders"] == 0
    assert ctx["summary"]["overdue_threshold_days"] == 30
    assert ctx["status_counts"] == {
        "open": 0,
        "closed": 0,
        "hold": 0,
        "unknown": 0,
    }
    assert ctx["cost_vs_budget"] == {
        "cost_to_date": 0.0,
        "budget": 0.0,
        "variance": 0.0,
        "variance_pct": None,
    }


def test_recommendations_route_cache_miss_writes_row(
    work_orders_client, monkeypatch, empty_engine, tenant_id,
):
    calls: list[dict[str, Any]] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append({"module": module, "kwargs": kwargs})
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(work_orders_insights, "generate_insight", _fake_generate)

    r = work_orders_client.get("/api/work-orders/recommendations")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["module"] == "work_orders"
    assert body["recommendations"][0]["affected_assets"] == ["overdue"]
    assert len(calls) == 1
    assert calls[0]["kwargs"]["tenant_id"] == tenant_id

    with sessionmaker(empty_engine)() as s:
        row = s.execute(
            select(LlmInsight).where(
                LlmInsight.tenant_id == tenant_id,
                LlmInsight.module == "work_orders",
            )
        ).scalar_one_or_none()
    assert row is not None
    assert row.revision_token == body["revision_token"]


def test_recommendations_route_cache_hit_skips_generate(
    work_orders_client, monkeypatch,
):
    calls: list[Any] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append(1)
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(work_orders_insights, "generate_insight", _fake_generate)

    first = work_orders_client.get("/api/work-orders/recommendations")
    second = work_orders_client.get("/api/work-orders/recommendations")
    assert first.status_code == 200
    assert second.status_code == 200
    assert len(calls) == 1
    assert first.json()["revision_token"] == second.json()["revision_token"]


def test_recommendations_route_refresh_forces_regeneration(
    work_orders_client, monkeypatch,
):
    calls: list[Any] = []

    def _fake_generate(module, ctx, prompt, **kwargs):
        calls.append(datetime.now(timezone.utc))
        return _fake_response(module, llm_module.hash_data_context(ctx))

    monkeypatch.setattr(work_orders_insights, "generate_insight", _fake_generate)

    work_orders_client.get("/api/work-orders/recommendations")
    work_orders_client.get("/api/work-orders/recommendations?refresh=true")
    assert len(calls) == 2
