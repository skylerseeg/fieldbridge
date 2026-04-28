"""Smoke tests for the integration harness itself.

These don't test any module — they test the *harness*. Every module
worker depends on `build_integrated_engine` doing what it claims, so a
regression here would cascade across the whole suite.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.models.tenant import SubscriptionTier, Tenant
from app.services.excel_marts import MART_MODULES
from tests.integration.harness import (
    build_integrated_engine,
    list_registered_mart_tables,
)


pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- #
# Engine bootstrap                                                            #
# --------------------------------------------------------------------------- #


class TestBuildIntegratedEngine:
    def test_returns_tuple_of_engine_and_tenant_id(self, tmp_path: Path):
        engine, tenant_id = build_integrated_engine(tmp_path)

        assert isinstance(engine, Engine)
        assert isinstance(tenant_id, str)
        # tenant_id is a UUID4 string.
        uuid.UUID(tenant_id)

    def test_tenant_row_persists(self, tmp_path: Path):
        engine, tenant_id = build_integrated_engine(tmp_path)

        with sessionmaker(engine)() as s:
            row = s.get(Tenant, tenant_id)

        assert row is not None
        assert row.slug == "vancon"
        assert row.tier is SubscriptionTier.INTERNAL

    def test_custom_tenant_overrides(self, tmp_path: Path):
        engine, tenant_id = build_integrated_engine(
            tmp_path,
            tenant_slug="acme",
            tenant_name="Acme Civil",
            tenant_email="ops@acme.test",
            tier=SubscriptionTier.GROWTH,
        )

        with sessionmaker(engine)() as s:
            row = s.get(Tenant, tenant_id)

        assert row.slug == "acme"
        assert row.company_name == "Acme Civil"
        assert row.tier is SubscriptionTier.GROWTH

    def test_two_engines_isolated(self, tmp_path: Path):
        a, _ = build_integrated_engine(tmp_path / "a")
        b, _ = build_integrated_engine(tmp_path / "b")

        assert a is not b
        assert a.url != b.url


# --------------------------------------------------------------------------- #
# Schema coverage                                                             #
# --------------------------------------------------------------------------- #


class TestRegisteredTables:
    def test_mart_tables_present_on_engine(self, tmp_path: Path):
        engine, _ = build_integrated_engine(tmp_path)
        actual = set(inspect(engine).get_table_names())

        expected = set(list_registered_mart_tables())
        assert expected, "harness reported zero mart tables — sanity broken"
        missing = expected - actual
        assert not missing, f"mart tables not created on engine: {missing}"

    def test_every_mart_module_has_a_table_or_marker(self):
        """Every mart module either declares a Table (TABLE_NAME set) or a
        well-known opt-out marker. Catches regressions where someone adds a
        mart submodule without wiring it into Base.metadata."""
        offenders: list[str] = []
        for mod in MART_MODULES:
            table_name = getattr(mod, "TABLE_NAME", None)
            if table_name is None:
                offenders.append(mod.__name__)

        assert not offenders, (
            "These mart modules are missing TABLE_NAME — they will not be "
            "created by build_integrated_engine: "
            f"{offenders}"
        )

    def test_core_tables_present(self, tmp_path: Path):
        """Tenant + ingest log + LLM insights are required for any
        integration test that exercises a router."""
        engine, _ = build_integrated_engine(tmp_path)
        actual = set(inspect(engine).get_table_names())

        for required in ("tenants", "ingest_log", "llm_insights"):
            assert required in actual, (
                f"core table missing: {required}. Did app.models import order break?"
            )


# --------------------------------------------------------------------------- #
# Round-trip: insert + read against a known mart                              #
# --------------------------------------------------------------------------- #


class TestRoundTrip:
    """If we can't write+read a row through the harness, every module
    integration test will fail in the same way. Catch it here, once."""

    def test_insert_and_select_against_mart_proposals(self, tmp_path: Path):
        engine, tenant_id = build_integrated_engine(tmp_path)

        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO mart_proposals "
                    "(tenant_id, job, owner, bid_type, county) "
                    "VALUES (:tenant_id, :job, :owner, :bid_type, :county)"
                ),
                {
                    "tenant_id": tenant_id,
                    "job": "Smoke Job",
                    "owner": "Harness Co",
                    "bid_type": "Pressurized Water Main",
                    "county": "Utah, UT",
                },
            )

        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT job, owner FROM mart_proposals WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            ).one()

        assert row.job == "Smoke Job"
        assert row.owner == "Harness Co"
