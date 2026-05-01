"""Reusable integration-test harness.

Factory contract:

    >>> from tests.integration.harness import build_integrated_engine
    >>> engine, tenant_id = build_integrated_engine(tmp_path)

The returned engine has:

* every mart Table from `app.services.excel_marts` registered against
  `Base.metadata` and `create_all()`-ed,
* core tables (`tenants`, `users`, `usage_events`, `ingest_log`,
  `llm_insights`) created,
* a single `vancon` reference tenant seeded with `tier=INTERNAL`.

Why a free function plus a fixture?
The free function is what cross-module tests reach for when they want
to build several engines (e.g. multi-tenant isolation tests). The
`integrated_engine` pytest fixture wraps it for the common path.

This file is **append-only by design** for module workers: if your
module needs a richer seed, add a `seed_<module>(engine, tenant_id)`
helper here so the next module can re-use it. Don't reach into module
service internals from the harness — keep the harness raw-SQL or
SQLAlchemy-core only.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Iterable

import pytest
from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.orm import sessionmaker

# Importing this package registers every mart Table on Base.metadata.
import app.services.excel_marts  # noqa: F401
from app.core.database import Base
from app.models.tenant import SubscriptionTier, Tenant, TenantStatus


DEFAULT_TENANT_SLUG = "vancon"
DEFAULT_TENANT_NAME = "VanCon Inc."
DEFAULT_TENANT_EMAIL = "admin@vancon.test"


def build_integrated_engine(
    db_dir: Path,
    *,
    tenant_slug: str = DEFAULT_TENANT_SLUG,
    tenant_name: str = DEFAULT_TENANT_NAME,
    tenant_email: str = DEFAULT_TENANT_EMAIL,
    tier: SubscriptionTier = SubscriptionTier.INTERNAL,
    db_filename: str = "integration.db",
) -> tuple[Engine, str]:
    """Spin up a fresh SQLite engine with all mart tables + one tenant.

    Returns
    -------
    (engine, tenant_id)
        ``engine`` — synchronous SQLAlchemy Engine pointing at a
        fresh file-backed SQLite database under ``db_dir``.
        ``tenant_id`` — UUID of the seeded tenant.
    """
    db_dir.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{db_dir / db_filename}"
    engine = create_engine(url, future=True)

    Base.metadata.create_all(engine)

    tenant_id = str(uuid.uuid4())
    with sessionmaker(engine)() as s:
        s.add(
            Tenant(
                id=tenant_id,
                slug=tenant_slug,
                company_name=tenant_name,
                contact_email=tenant_email,
                tier=tier,
                status=TenantStatus.ACTIVE,
            )
        )
        s.commit()

    return engine, tenant_id


def list_registered_mart_tables() -> list[str]:
    """Every table name registered on ``Base.metadata`` that starts with ``mart_``.

    Useful for assertions in cross-module tests ("did the integration
    harness register the productivity mart?") without coupling to
    ``MART_MODULES``.
    """
    return sorted(name for name in Base.metadata.tables.keys() if name.startswith("mart_"))


def assert_tables_present(engine: Engine, expected: Iterable[str]) -> None:
    """Defensive helper — module integration tests can use this to fail fast
    if a required mart Table didn't actually get created."""
    insp = inspect(engine)
    actual = set(insp.get_table_names())
    missing = [t for t in expected if t not in actual]
    if missing:
        raise AssertionError(
            f"Integration harness is missing required tables: {missing}. "
            f"Verify app.services.excel_marts.__init__.py imports them."
        )


@pytest.fixture
def integrated_engine(tmp_path: Path) -> Engine:
    """The common-case fixture: engine pre-seeded with one tenant."""
    engine, _ = build_integrated_engine(tmp_path)
    return engine


@pytest.fixture
def integrated_tenant_id(tmp_path: Path) -> tuple[Engine, str]:
    """Fixture variant that hands you both the engine and the tenant id."""
    return build_integrated_engine(tmp_path)
