"""
Shared pytest fixtures.

Every ingest test uses a fresh file-backed SQLite DB so we exercise a real
dialect with real UPSERT semantics, while staying entirely offline.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

# app.models.__init__ imports from `fieldbridge.saas.*`, which requires the
# repo root (one level above `fieldbridge/`) to be on sys.path. Uvicorn gets
# this for free because it runs from the repo root; pytest does not.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest  # noqa: E402
from sqlalchemy import (
    Column,
    Float,
    MetaData,
    String,
    Table,
    create_engine,
)
from sqlalchemy.orm import sessionmaker

# Import the Base + models so create_all knows about ingest_log + tenants.
from app.core.database import Base  # noqa: F401
from app.models.tenant import SubscriptionTier, Tenant, TenantStatus
from app.models.ingest_log import IngestLog  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.usage import UsageEvent  # noqa: F401
from app.models.llm_insight import LlmInsight  # noqa: F401


@pytest.fixture
def sqlite_db(tmp_path: Path) -> str:
    """Sync SQLite URL unique to each test."""
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture
def engine(sqlite_db):
    eng = create_engine(sqlite_db, future=True)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def tenant_id(engine) -> str:
    """Insert a dummy tenant so FK constraints on ingest_log pass."""
    tid = str(uuid.uuid4())
    with sessionmaker(engine)() as s:
        s.add(
            Tenant(
                id=tid,
                slug="test-tenant",
                company_name="Test Inc.",
                contact_email="admin@test.example",
                tier=SubscriptionTier.INTERNAL,
                status=TenantStatus.ACTIVE,
            )
        )
        s.commit()
    return tid


@pytest.fixture
def mart_table(engine):
    """A representative mart target table with a composite unique key.

    Columns mirror the minimum shape of a real mart:
      (tenant_id, id) is the dedupe / conflict target.
    """
    md = MetaData()
    t = Table(
        "mart_test_sample",
        md,
        Column("tenant_id", String(36), primary_key=True),
        Column("id", String(40), primary_key=True),
        Column("description", String(200)),
        Column("amount", Float),
    )
    md.create_all(engine)
    return t


@pytest.fixture
def mart_row_hash_table(engine):
    """A mart with no natural key — uses _row_hash for dedupe."""
    md = MetaData()
    t = Table(
        "mart_test_row_hash",
        md,
        Column("tenant_id", String(36), primary_key=True),
        Column("_row_hash", String(32), primary_key=True),
        Column("name", String(200)),
        Column("phone", String(40)),
    )
    md.create_all(engine)
    return t
