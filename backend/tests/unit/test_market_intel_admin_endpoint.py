"""Tests for ``POST /api/v1/market-intel/admin/run-itd-pipeline``.

Strategy mirrors ``test_itd_pipeline.py``: aiosqlite in-memory engine,
all tables created, SHARED_NETWORK tenant seeded, ``HttpFetcher``
mocked via ``pytest-httpx``. The HTTP layer is exercised through
``httpx.AsyncClient(transport=ASGITransport)`` so the route's auth
dependencies + response model serialization both run.

Locked-in contract:

  * 200 + ``ITDPipelineRunResponse`` shape on a successful admin call
  * 403 when the caller's role isn't ``fieldbridge_admin``
  * 401 when no token is presented
  * The endpoint is idempotent: re-calling on identical fixture
    bytes increments ``skipped_already_ingested`` instead of writing
    duplicates
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import get_current_user
from app.core.database import Base, get_db
from app.core.seed import SHARED_NETWORK_TENANT_ID
from app.models.tenant import (
    SubscriptionTier,
    Tenant,
    TenantKind,
    TenantStatus,
)
from app.models.user import User, UserRole
from app.modules.market_intel.router import router as market_intel_router
from app.services.market_intel.scrapers._fetcher import HttpFetcher, RateLimiter
from app.services.market_intel.scrapers.state_dot.itd import INDEX_URL
import app.services.market_intel.pipeline as pipeline_module


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "itd"


# ---------------------------------------------------------------------------
# Helpers (copied/condensed from test_itd_pipeline.py — same shape)

def _load_manifest_or_skip() -> dict:
    p = FIXTURES_DIR / "MANIFEST.json"
    if not p.exists():
        pytest.skip(f"ITD fixtures not committed at {FIXTURES_DIR}")
    return json.loads(p.read_text())


def _v1_fixtures(n: int) -> list[str]:
    manifest = _load_manifest_or_skip()
    return sorted(
        name for name, rec in manifest["fixtures"].items()
        if rec["template_version"] == "aashtoware_v1"
    )[:n]


def _build_index_html(filenames: list[str]) -> str:
    links = "\n".join(
        f'<a href="https://apps.itd.idaho.gov/apps/contractors/{name}">{name}</a>'
        for name in filenames
    )
    return f"<html><body>{links}</body></html>"


def _register_robots(httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://itd.idaho.gov/robots.txt",
        status_code=200,
        text="User-agent: *\nDisallow: /wp-admin/\n",
    )
    httpx_mock.add_response(
        method="GET",
        url="https://apps.itd.idaho.gov/robots.txt",
        status_code=200,
        text="User-agent: *\nAllow: /\n",
    )


def _register_index(httpx_mock, pdf_filenames: list[str]) -> None:
    httpx_mock.add_response(
        method="GET",
        url=INDEX_URL,
        status_code=200,
        text=_build_index_html(pdf_filenames),
        headers={"Content-Type": "text/html; charset=utf-8"},
    )


def _register_pdf(httpx_mock, filename: str) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"https://apps.itd.idaho.gov/apps/contractors/{filename}",
        status_code=200,
        content=(FIXTURES_DIR / filename).read_bytes(),
        headers={"Content-Type": "application/pdf"},
    )


# ---------------------------------------------------------------------------
# Fixtures: app + db + auth overrides

@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        session.add(
            Tenant(
                id=SHARED_NETWORK_TENANT_ID,
                slug="shared-network",
                company_name="Shared Bid Network",
                contact_email="shared@fieldbridge.test",
                tier=SubscriptionTier.INTERNAL,
                status=TenantStatus.ACTIVE,
                kind=TenantKind.SHARED_DATASET,
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


def _make_admin_user() -> User:
    return User(
        id=str(uuid.uuid4()),
        tenant_id=SHARED_NETWORK_TENANT_ID,
        email="admin@fieldbridge.test",
        hashed_password="x",
        full_name="Test Admin",
        role=UserRole.FIELDBRIDGE_ADMIN,
        is_active=True,
        is_verified=True,
    )


def _make_pm_user() -> User:
    """Non-admin role; should hit 403 on the admin endpoint."""
    return User(
        id=str(uuid.uuid4()),
        tenant_id=SHARED_NETWORK_TENANT_ID,
        email="pm@fieldbridge.test",
        hashed_password="x",
        full_name="Test PM",
        role=UserRole.PROJECT_MANAGER,
        is_active=True,
        is_verified=True,
    )


def _build_app(db: AsyncSession, current_user: User | None) -> FastAPI:
    """FastAPI app with router mounted + overrides applied. ``current_user``
    is ``None`` to simulate no token (which our overridden auth dep
    returns by raising 401)."""
    app = FastAPI()
    app.include_router(market_intel_router, prefix="/api/v1/market-intel")

    async def _override_db():
        yield db

    async def _override_user():
        if current_user is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="not authenticated")
        return current_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return app


def _patch_pipeline_fetcher(monkeypatch):
    """ITDPipeline() inside the endpoint constructs its own fetcher;
    replace with a no-rate-limit fetcher for test speed."""
    original_init = pipeline_module.ITDPipeline.__init__

    def fast_init(self, **kwargs):
        if kwargs.get("fetcher") is None:
            kwargs["fetcher"] = HttpFetcher(
                rate_limiter=RateLimiter(min_delay_s=0.0, max_delay_s=0.0),
            )
        return original_init(self, **kwargs)

    monkeypatch.setattr(pipeline_module.ITDPipeline, "__init__", fast_init)


# ---------------------------------------------------------------------------
# (1) Happy path: admin role, fixtures mocked, counters returned

async def test_admin_endpoint_returns_counters(
    httpx_mock, db_session: AsyncSession, monkeypatch,
):
    fixtures = _v1_fixtures(3)
    _register_robots(httpx_mock)
    _register_index(httpx_mock, fixtures)
    for name in fixtures:
        _register_pdf(httpx_mock, name)
    _patch_pipeline_fetcher(monkeypatch)

    app = _build_app(db_session, _make_admin_user())
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/market-intel/admin/run-itd-pipeline")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    expected_keys = {
        "fetched", "parsed", "written",
        "skipped_robots", "skipped_fetch_error",
        "skipped_legacy_template", "skipped_parse_error",
        "skipped_already_ingested",
        "duration_ms",
    }
    assert set(body.keys()) == expected_keys
    assert body["fetched"] == 3
    assert body["parsed"] == 3
    assert body["written"] == 3
    assert body["skipped_legacy_template"] == 0
    assert body["duration_ms"] >= 0


# ---------------------------------------------------------------------------
# (2) Idempotency over HTTP: second POST writes 0 new rows

async def test_admin_endpoint_idempotent(
    httpx_mock, db_session: AsyncSession, monkeypatch,
):
    fixtures = _v1_fixtures(2)
    # Each HTTP call constructs a fresh ITDPipeline → fresh RobotsCache,
    # so robots.txt + index + each PDF are fetched twice across the two
    # POSTs. Register each response twice.
    for _ in range(2):
        _register_robots(httpx_mock)
        _register_index(httpx_mock, fixtures)
        for name in fixtures:
            _register_pdf(httpx_mock, name)
    _patch_pipeline_fetcher(monkeypatch)

    app = _build_app(db_session, _make_admin_user())
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = (await client.post("/api/v1/market-intel/admin/run-itd-pipeline")).json()
        second = (await client.post("/api/v1/market-intel/admin/run-itd-pipeline")).json()

    assert first["written"] == 2
    assert first["skipped_already_ingested"] == 0
    assert second["written"] == 0
    assert second["skipped_already_ingested"] == 2


# ---------------------------------------------------------------------------
# (3) Non-admin role → 403

async def test_admin_endpoint_rejects_non_admin(
    db_session: AsyncSession, monkeypatch,
):
    """A user with role=project_manager hits 403, even with a valid
    token. Crucial — the n8n cron token MUST be a fieldbridge_admin
    JWT or it silently does nothing useful."""
    _patch_pipeline_fetcher(monkeypatch)

    app = _build_app(db_session, _make_pm_user())
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/market-intel/admin/run-itd-pipeline")

    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# (4) No auth → 401

async def test_admin_endpoint_rejects_unauthenticated(
    db_session: AsyncSession, monkeypatch,
):
    _patch_pipeline_fetcher(monkeypatch)

    app = _build_app(db_session, current_user=None)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/market-intel/admin/run-itd-pipeline")

    assert resp.status_code == 401, resp.text
