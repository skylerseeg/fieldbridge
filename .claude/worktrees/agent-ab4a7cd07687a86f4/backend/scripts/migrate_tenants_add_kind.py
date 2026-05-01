"""One-shot migration: add ``kind`` column to ``tenants`` table.

The Tenant SQLAlchemy model now declares a ``kind`` enum column
(customer | shared_dataset | internal_test). Postgres environments
that were seeded before this column existed need a manual
ALTER TABLE — ``Base.metadata.create_all`` is CREATE-IF-NOT-EXISTS
only and won't add columns to existing tables.

Run from Render Shell after the new image deploys:

    python scripts/migrate_tenants_add_kind.py

Idempotent: ``ADD COLUMN IF NOT EXISTS`` + ``CREATE TYPE IF NOT
EXISTS``. Safe to run multiple times.

After this lands, ``python -m app.core.seed`` will:
  * UPSERT the shared-network sentinel tenant (kind=shared_dataset)
  * Leave existing rows (e.g. VanCon prod) at the default 'customer'

This script is one-time. After all live environments have run it,
delete this file in a follow-up commit.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# sys.path bootstrap so this script runs as a standalone CLI from
# /app/backend in the Render Shell, matching the run_ingest.py pattern.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import text  # noqa: E402

from app.core.database import engine  # noqa: E402

log = logging.getLogger("fieldbridge.migrate.tenants_add_kind")

# Postgres-specific: enum type creation is conditional on it not
# already existing. SQLAlchemy's Enum type would CREATE TYPE on a
# fresh install, but ALTER TABLE in a live env needs us to do it
# manually first.
DDL = [
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = 'tenantkind'
        ) THEN
            CREATE TYPE tenantkind AS ENUM (
                'customer', 'shared_dataset', 'internal_test'
            );
        END IF;
    END
    $$;
    """,
    """
    ALTER TABLE tenants
        ADD COLUMN IF NOT EXISTS kind tenantkind
        NOT NULL DEFAULT 'customer';
    """,
]


async def migrate() -> None:
    async with engine.begin() as conn:
        for stmt in DDL:
            await conn.execute(text(stmt))
            log.info("Applied: %s", stmt.strip().split("\n")[0][:80])
    log.info("tenants.kind migration complete.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )
    asyncio.run(migrate())
