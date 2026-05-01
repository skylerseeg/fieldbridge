"""Create all mart tables + ensure the VanCon reference tenant exists.

Synchronous so it can run ahead of ``python -m app.core.ingest`` without
asyncio plumbing. Safe to re-run: ``Base.metadata.create_all`` is idempotent,
and the tenant upsert only inserts when slug is missing.

Usage:
    python scripts/create_mart_tables.py                  # uses DATABASE_URL
    python scripts/create_mart_tables.py --database-url sqlite:///./.local/ingest_run.db
"""
from __future__ import annotations

import argparse
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Run directly from the scripts/ dir or via `make`: make the backend/ root
# importable without requiring `python -m` or an installed package.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

# Importing this package triggers every mart's schema.py, which registers
# Tables against Base.metadata, and every ingest.py, which populates the
# job registry. Keep the import even if no symbols from it are used directly.
import app.services.excel_marts  # noqa: F401
from app.core.config import settings
from app.core.database import Base
from app.core.ingest import _sync_url, get_registry
from app.models.tenant import SubscriptionTier, Tenant, TenantStatus

log = logging.getLogger("fieldbridge.create_mart_tables")


def _ensure_tenant(SessionLocal, slug: str) -> str:
    """Ensure a tenant row with the given slug exists; return its id."""
    with SessionLocal() as s:
        tenant = s.execute(
            select(Tenant).where(Tenant.slug == slug)
        ).scalar_one_or_none()

        if tenant:
            log.info("Tenant %r already present (id=%s)", slug, tenant.id)
            return tenant.id

        tenant = Tenant(
            id=str(uuid.uuid4()),
            slug=slug,
            company_name="VanCon Inc." if slug == "vancon" else slug,
            contact_email=f"admin@{slug}.local",
            contact_name=f"{slug} admin",
            tier=SubscriptionTier.INTERNAL if slug == "vancon"
                 else SubscriptionTier.STARTER,
            status=TenantStatus.ACTIVE,
            onboarding_step=5,
            vista_connection_verified=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        s.add(tenant)
        s.commit()
        log.info("Created tenant %r (id=%s)", slug, tenant.id)
        return tenant.id


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create all mart tables + ensure reference tenant."
    )
    parser.add_argument(
        "--database-url", default=None,
        help="sync DB URL; defaults to settings.database_url (normalized to sync)",
    )
    parser.add_argument(
        "--tenant-slug", default="vancon",
        help="tenant slug to ensure exists (default: vancon)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    url = args.database_url or _sync_url(settings.database_url)
    log.info("Using database URL: %s", url)

    engine = create_engine(url, future=True)
    SessionLocal = sessionmaker(engine, expire_on_commit=False)

    # Import every app model so Base.metadata knows the non-mart tables
    # (tenants, users, ingest_log, …). excel_marts is already imported above.
    import app.models  # noqa: F401,E402

    Base.metadata.create_all(engine)
    log.info("Tables created/verified: %d total", len(Base.metadata.tables))

    registry = get_registry()
    log.info("Registered ingest jobs: %d", len(registry))
    for name in sorted(registry):
        log.info("  - %s", name)

    tenant_id = _ensure_tenant(SessionLocal, args.tenant_slug)
    log.info("Ready. tenant=%r id=%s", args.tenant_slug, tenant_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
