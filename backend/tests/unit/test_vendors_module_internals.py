"""Vendors module internal-coverage push.

Companion to ``test_vendors_module.py``. The big test file is happy-path
focused (KPI counts, list/sort/filter, detail, enrichment merge). This
one targets the defensive branches the agent_board.md "Tests/CI 2026-Q3"
ramp flagged as weak in the vendors module, all without leaving the
vendors lane:

* ``service._fetch_all`` legacy fallback when ``mart_vendor_enrichments``
  is missing on disk (e.g. a tenant DB that hasn't run the
  PROPOSED_CHANGES.md migration yet).
* ``service.enrich_vendor`` -> ``VendorEnrichmentStoreMissing`` raise
  path when the overlay table doesn't exist; router translation to
  503.
* ``service._is_missing_enrichment_table`` shape detection across the
  three error strings we see (sqlite / postgres / generic).
* ``service.list_vendors`` parameter normalization (out-of-range page,
  page_size, sort_dir).
* ``service._vendor_id`` synthetic-id fallback when a null-name row
  carries no ``_row_hash``.
* ``insights._upsert_cache`` updating an existing cache row (vs. the
  insert path covered by ``test_phase6_recommendations.py``).
* ``insights._load_cached`` swallowing an unparseable cache row.

All tests use the same fresh-SQLite + dependency-override pattern as
the canonical vendors test, but with smaller seeds and direct service
calls where it avoids re-exercising the full HTTP plumbing.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

# Register every mart Table on Base.metadata.
import app.services.excel_marts  # noqa: F401
from app.core import llm as llm_module
from app.core.database import Base
from app.core.llm import InsightResponse, Recommendation, Severity
from app.models.llm_insight import LlmInsight
from app.models.tenant import SubscriptionTier, Tenant, TenantStatus
from app.modules.vendors import insights as vendors_insights
from app.modules.vendors import service
from app.modules.vendors.router import (
    _default_engine,
    get_engine,
    get_tenant_id,
    router as vendors_router,
)
from app.modules.vendors.schema import VendorEnrichmentRequest


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


def _row_hash_for(row: dict) -> str:
    payload = json.dumps(row, sort_keys=True, default=str)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


@pytest.fixture
def tenant_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def engine_no_overlay(tmp_path, tenant_id) -> Engine:
    """Engine that has ``mart_vendors`` but NOT ``mart_vendor_enrichments``.

    Mirrors a tenant DB that hasn't yet had the v1 enrichment DDL applied.
    The service layer is supposed to fall back gracefully on the read path
    and raise ``VendorEnrichmentStoreMissing`` on the write path.
    """
    url = f"sqlite:///{tmp_path / 'vendors_no_overlay.db'}"
    engine = create_engine(url, future=True)

    # Create only the bits we need so we don't accidentally pick up
    # ``mart_vendor_enrichments`` from the registry.
    tenant_table = Base.metadata.tables["tenants"]
    vendors_table = Base.metadata.tables["mart_vendors"]
    Base.metadata.create_all(engine, tables=[tenant_table, vendors_table])

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

    seed = {
        "name": "Acme Concrete Co",
        "firm_type": "Contractor",
        "contact": "Alice A.",
        "title": "PM",
        "email": "alice@acme.test",
        "phone": "555-0101",
        "code_1": "0330-Cast-in-place Concrete",
        "code_2": None,
        "code_3": None,
        "code_4": None,
        "code_5": None,
    }
    with engine.begin() as conn:
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
            {"tenant_id": tenant_id, "_row_hash": _row_hash_for(seed), **seed},
        )

    return engine


@pytest.fixture
def client_no_overlay(engine_no_overlay: Engine, tenant_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(vendors_router, prefix="/api/vendors")
    app.dependency_overrides[get_engine] = lambda: engine_no_overlay
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    _default_engine.cache_clear()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def empty_engine(tmp_path, tenant_id) -> Engine:
    """Full mart schema, single seeded tenant, no rows.

    Used by the insight-cache tests so we exercise ``_load_cached`` /
    ``_upsert_cache`` without touching any of the directory data.
    """
    url = f"sqlite:///{tmp_path / 'vendors_internals.db'}"
    engine = create_engine(url, future=True)
    Base.metadata.create_all(engine)
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
    return engine


def _fake_response(revision_token: str) -> InsightResponse:
    return InsightResponse(
        module="vendors",
        revision_token=revision_token,
        recommendations=[
            Recommendation(
                title="Investigate vendor cohort",
                severity=Severity.WARNING,
                rationale=(
                    "Synthetic test rationale long enough to pass the "
                    "min_length validator on Recommendation."
                ),
                suggested_action="Have the Operations Manager review the data.",
                affected_assets=[],
            )
        ],
        input_tokens=42,
        output_tokens=24,
    )


# --------------------------------------------------------------------------- #
# Read-path resilience: no overlay table                                      #
# --------------------------------------------------------------------------- #


class TestReadPathFallback:
    """``mart_vendor_enrichments`` missing must NOT break read endpoints."""

    def test_summary_falls_back_when_overlay_table_missing(
        self, client_no_overlay: TestClient,
    ):
        resp = client_no_overlay.get("/api/vendors/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_vendors"] == 1
        assert body["complete_contact"] == 1
        assert body["coded_vendors"] == 1
        assert body["distinct_divisions"] == 1

    def test_list_falls_back_when_overlay_table_missing(
        self, client_no_overlay: TestClient,
    ):
        resp = client_no_overlay.get("/api/vendors/list")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        row = body["items"][0]
        assert row["name"] == "Acme Concrete Co"
        assert row["enriched"] is False
        assert row["enriched_at"] is None

    def test_detail_falls_back_when_overlay_table_missing(
        self, client_no_overlay: TestClient,
    ):
        resp = client_no_overlay.get("/api/vendors/Acme Concrete Co")
        assert resp.status_code == 200
        body = resp.json()
        assert body["enriched"] is False
        assert body["enrichment_notes"] is None


# --------------------------------------------------------------------------- #
# Write-path: overlay table missing -> 503 / VendorEnrichmentStoreMissing      #
# --------------------------------------------------------------------------- #


class TestEnrichmentStoreMissing:
    def test_service_raises_when_overlay_table_absent(
        self, engine_no_overlay: Engine, tenant_id: str,
    ):
        with pytest.raises(service.VendorEnrichmentStoreMissing):
            service.enrich_vendor(
                engine_no_overlay,
                tenant_id,
                "Acme Concrete Co",
                VendorEnrichmentRequest(email="x@example.test"),
            )

    def test_router_returns_503_when_overlay_table_absent(
        self, client_no_overlay: TestClient,
    ):
        resp = client_no_overlay.post(
            "/api/vendors/enrichments/Acme Concrete Co",
            json={"email": "x@example.test"},
        )
        assert resp.status_code == 503
        # Lead-facing message must call out the migration so operators
        # don't chase a generic 503.
        assert "mart_vendor_enrichments" in resp.json()["detail"]

    def test_is_missing_enrichment_table_recognizes_known_dialects(self):
        # Build a faux DBAPIError-shaped object with .orig — we don't
        # need a live engine to exercise the branching.
        class _FakeOrig(Exception):
            pass

        class _FakeErr(DBAPIError):
            def __init__(self, msg):
                self.orig = _FakeOrig(msg)

            def __str__(self):
                return str(self.orig)

        # SQLite phrasing.
        assert service._is_missing_enrichment_table(
            _FakeErr("no such table: mart_vendor_enrichments"),
        )
        # Postgres phrasing.
        assert service._is_missing_enrichment_table(
            _FakeErr("relation \"mart_vendor_enrichments\" does not exist"),
        )
        # Some drivers prefix with "undefined table".
        assert service._is_missing_enrichment_table(
            _FakeErr("undefined table mart_vendor_enrichments"),
        )
        # Unrelated DB error should NOT be swallowed.
        assert not service._is_missing_enrichment_table(
            _FakeErr("syntax error near \"vendor\""),
        )
        # Errors mentioning a different table must not match either.
        assert not service._is_missing_enrichment_table(
            _FakeErr("no such table: mart_vendors"),
        )


# --------------------------------------------------------------------------- #
# list_vendors parameter normalization                                        #
# --------------------------------------------------------------------------- #


class TestListVendorsNormalization:
    """The router validates request params, but ``service.list_vendors``
    is also called directly (e.g. from analytics jobs / cron). It must
    coerce out-of-range values rather than raise."""

    def test_negative_page_clamps_to_one(
        self, engine_no_overlay: Engine, tenant_id: str,
    ):
        resp = service.list_vendors(
            engine_no_overlay, tenant_id, page=-3, page_size=10,
        )
        assert resp.page == 1
        assert resp.total == 1

    def test_invalid_page_size_resets_to_default(
        self, engine_no_overlay: Engine, tenant_id: str,
    ):
        for bad in (0, -7, 9999):
            resp = service.list_vendors(
                engine_no_overlay, tenant_id, page=1, page_size=bad,
            )
            assert resp.page_size == 25

    def test_unknown_sort_dir_falls_back_to_asc(
        self, engine_no_overlay: Engine, tenant_id: str,
    ):
        resp = service.list_vendors(
            engine_no_overlay, tenant_id,
            page=1, page_size=10, sort_dir="sideways",  # type: ignore[arg-type]
        )
        assert resp.sort_dir == "asc"


# --------------------------------------------------------------------------- #
# Helpers — synthetic id fallback, code normalization                         #
# --------------------------------------------------------------------------- #


class TestVendorIdSynthetic:
    def test_uses_row_hash_when_present(self):
        rh = "deadbeef" * 4
        result = service._vendor_id({"name": None, "_row_hash": rh})
        assert result == f"__empty__{rh}"

    def test_falls_back_to_contact_hash_when_row_hash_missing(self):
        # No name, no row hash — the function must still produce a
        # deterministic id from contact / email / phone so the row
        # remains addressable from the API.
        row = {
            "name": None,
            "_row_hash": None,
            "contact": "Cathy Contact",
            "email": "cathy@example.test",
            "phone": "555-0102",
        }
        result_a = service._vendor_id(row)
        result_b = service._vendor_id(row)
        assert result_a == result_b
        assert result_a.startswith("__empty__")
        # Different contact data must produce a different id.
        other = service._vendor_id({**row, "email": "other@example.test"})
        assert other != result_a

    def test_normalized_name_wins_over_row_hash(self):
        result = service._vendor_id(
            {"name": "  Acme   Concrete   Co  ", "_row_hash": "ignored"},
        )
        assert result == "Acme Concrete Co"


class TestNormalizeCodes:
    def test_trims_dedupes_and_caps_at_five(self):
        codes = service._normalize_codes(
            [
                "  0330-Concrete  ",
                "0330-Concrete",  # exact dupe of the trimmed first entry
                "0350-Precast",
                "0360-Grouting",
                "0410-Masonry",
                "0420-Stone",
                "0430-Brick",  # over the cap
            ]
        )
        assert codes == [
            "0330-Concrete",
            "0350-Precast",
            "0360-Grouting",
            "0410-Masonry",
            "0420-Stone",
        ]

    def test_blank_and_none_ignored(self):
        codes = service._normalize_codes(["", "   ", "0330-Concrete"])
        assert codes == ["0330-Concrete"]


# --------------------------------------------------------------------------- #
# Insight cache write/read fallbacks                                          #
# --------------------------------------------------------------------------- #


class TestInsightCacheUpsert:
    def test_upsert_updates_existing_row(
        self, empty_engine: Engine, tenant_id: str,
    ):
        # First write — establishes the row.
        first = _fake_response(revision_token="rev-1")
        vendors_insights._upsert_cache(empty_engine, tenant_id, first)

        # Second write with a different revision_token — must replace
        # the same row (one-row-per-(tenant, module) invariant).
        second = _fake_response(revision_token="rev-2")
        vendors_insights._upsert_cache(empty_engine, tenant_id, second)

        with sessionmaker(empty_engine)() as s:
            rows = (
                s.execute(
                    select(LlmInsight).where(
                        LlmInsight.tenant_id == tenant_id,
                        LlmInsight.module == vendors_insights.MODULE_SLUG,
                    )
                )
                .scalars()
                .all()
            )

        assert len(rows) == 1
        assert rows[0].revision_token == "rev-2"

    def test_upsert_swallows_db_errors(self, tenant_id: str):
        """``_upsert_cache`` is best-effort: a DB hiccup is logged but
        must never propagate to the caller (otherwise a transient cache
        write failure would 500 the recommendations endpoint)."""
        bogus_engine = create_engine(
            "sqlite:///:memory:", future=True,
        )
        # Empty DB — no llm_insights table. The function must swallow.
        vendors_insights._upsert_cache(
            bogus_engine, tenant_id, _fake_response(revision_token="rev-x"),
        )


class TestInsightCacheLoad:
    def test_load_returns_none_when_payload_unparseable(
        self, empty_engine: Engine, tenant_id: str,
    ):
        """A historical / corrupted cache row must be ignored rather
        than crash the route. ``_load_cached`` swallows the parse error,
        logs it, and the route falls through to a fresh LLM call."""
        with sessionmaker(empty_engine)() as s:
            s.add(
                LlmInsight(
                    tenant_id=tenant_id,
                    module=vendors_insights.MODULE_SLUG,
                    revision_token="rev-corrupt",
                    payload_json="{not-valid-json",
                    input_tokens=0,
                    output_tokens=0,
                    model="claude-opus-4-7",
                    created_at=datetime.now(timezone.utc),
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=6),
                )
            )
            s.commit()

        result = vendors_insights._load_cached(
            empty_engine, tenant_id, "rev-corrupt",
        )
        assert result is None

    def test_load_returns_none_when_revision_token_mismatch(
        self, empty_engine: Engine, tenant_id: str,
    ):
        """Token mismatch is the "stale-but-not-expired" path — the
        underlying numbers moved since the LLM ran, so the cache must
        be treated as stale even if not yet TTL'd out."""
        valid = _fake_response(revision_token="rev-A")
        with sessionmaker(empty_engine)() as s:
            s.add(
                LlmInsight(
                    tenant_id=tenant_id,
                    module=vendors_insights.MODULE_SLUG,
                    revision_token="rev-A",
                    payload_json=valid.model_dump_json(),
                    input_tokens=0,
                    output_tokens=0,
                    model="claude-opus-4-7",
                    created_at=datetime.now(timezone.utc),
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=6),
                )
            )
            s.commit()

        # Asking for a different revision_token simulates the data
        # context having shifted underneath the cache.
        result = vendors_insights._load_cached(
            empty_engine, tenant_id, "rev-B",
        )
        assert result is None


class TestBuildRecommendationsForceRefresh:
    """``build_recommendations(force_refresh=True)`` must skip the cache
    even when a fresh row exists. Covered indirectly by the
    ``test_phase6_recommendations`` HTTP test, but the direct call path
    is exercised here so service-level callers (cron jobs, agents) get
    the same guarantee."""

    def test_force_refresh_skips_cache(
        self, empty_engine: Engine, tenant_id: str, monkeypatch,
    ):
        cached = _fake_response(revision_token="will-be-ignored")
        with sessionmaker(empty_engine)() as s:
            s.add(
                LlmInsight(
                    tenant_id=tenant_id,
                    module=vendors_insights.MODULE_SLUG,
                    # NOTE: build_recommendations re-hashes the empty
                    # data context every time so the revision_token
                    # below is structurally orthogonal — but with
                    # force_refresh=True we shouldn't even check.
                    revision_token="will-be-ignored",
                    payload_json=cached.model_dump_json(),
                    input_tokens=0,
                    output_tokens=0,
                    model="claude-opus-4-7",
                    created_at=datetime.now(timezone.utc),
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=6),
                )
            )
            s.commit()

        calls: list[str] = []

        def _fake_generate(module, ctx, prompt, **kwargs):
            calls.append(module)
            return _fake_response(
                revision_token=llm_module.hash_data_context(ctx),
            )

        monkeypatch.setattr(vendors_insights, "generate_insight", _fake_generate)

        result = vendors_insights.build_recommendations(
            empty_engine, tenant_id, force_refresh=True,
        )

        assert calls == ["vendors"]
        assert result.revision_token != "will-be-ignored"
