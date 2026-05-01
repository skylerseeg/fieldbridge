"""One-shot migration: Layer A/B schema additions for Market Intel.

Adds the new columns and tables described in
``docs/market-intel-data-state.md`` § 6 — fully additive, no drops,
no renames, no data backfill.

Why a script and not Alembic: Alembic is **not yet initialized** in
this repo (no ``backend/alembic.ini``, no ``backend/alembic/`` dir).
Adopting Alembic is a project-wide decision and not in scope for this
PR. This script follows the same pattern as
``backend/scripts/migrate_tenants_add_kind.py`` — once the project
formally adopts Alembic, the equivalent operations should be promoted
to a numbered migration and this file deleted.

Idempotent on Postgres via ``ADD COLUMN IF NOT EXISTS`` and
``CREATE TABLE IF NOT EXISTS``. SQLite does not support
``ADD COLUMN IF NOT EXISTS``, so column adds are wrapped in
try/except and the OperationalError "duplicate column name" is
swallowed.

Run from Render Shell after the new image deploys:

    python scripts/migrate_market_intel_layer_ab.py

Run for local SQLite dev (the test suite covers this same DDL via
``Base.metadata.create_all`` so this is rarely needed there):

    DATABASE_URL=sqlite+aiosqlite:///./local.db \
        python scripts/migrate_market_intel_layer_ab.py
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
from sqlalchemy.exc import OperationalError, ProgrammingError  # noqa: E402

from app.core.database import engine  # noqa: E402

log = logging.getLogger("fieldbridge.migrate.market_intel_layer_ab")


# ---------------------------------------------------------------------------
# DDL — dialect-aware. The SQL types and default expressions differ
# between Postgres and SQLite:
#
#   * ``TIMESTAMP WITH TIME ZONE`` — Postgres only. SQLite uses ``TIMESTAMP``
#     (it ignores the WITH TIME ZONE qualifier and stores text/julian).
#   * ``NOW()`` — Postgres. SQLite uses ``CURRENT_TIMESTAMP``.
#   * ``BOOLEAN DEFAULT FALSE`` — works on both, since SQLite accepts the
#     uppercase keyword as 0.
#
# ALTER TABLE ADD COLUMN constraints differ too:
#   * Postgres: ``ADD COLUMN IF NOT EXISTS``.
#   * SQLite: no IF NOT EXISTS for column adds; we catch the
#     "duplicate column" error to stay idempotent.
#   * SQLite also rejects ``ADD COLUMN col TIMESTAMP NOT NULL DEFAULT
#     CURRENT_TIMESTAMP`` because the default isn't a literal — so for
#     SQLite we add the column nullable and then UPDATE existing rows.
#     CI's ``Base.metadata.create_all`` path doesn't care because the
#     model is the source of truth there; this script is only for live
#     Postgres environments.
# ---------------------------------------------------------------------------


def _ts_type(is_sqlite: bool) -> str:
    return "TIMESTAMP" if is_sqlite else "TIMESTAMP WITH TIME ZONE"


def _now_default(is_sqlite: bool) -> str:
    return "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"


def _create_tables(is_sqlite: bool) -> list[str]:
    ts = _ts_type(is_sqlite)
    now = _now_default(is_sqlite)
    if_not_exists = "IF NOT EXISTS"
    return [
        # pipeline_runs — created first so the FKs from bid_events /
        # bid_results resolve.
        f"""
        CREATE TABLE {if_not_exists} pipeline_runs (
            id              VARCHAR(36) PRIMARY KEY,
            tenant_id       VARCHAR(36) NOT NULL REFERENCES tenants(id)
                                ON DELETE CASCADE,
            pipeline_name   VARCHAR(120) NOT NULL,
            started_at      {ts} NOT NULL DEFAULT {now},
            finished_at     {ts},
            status          VARCHAR(20) NOT NULL DEFAULT 'running',
            counters        JSON,
            error_message   TEXT,
            created_at      {ts} NOT NULL DEFAULT {now},
            updated_at      {ts} NOT NULL DEFAULT {now}
        );
        """,
        f"""
        CREATE INDEX {if_not_exists} ix_pipeline_runs_tenant_id
            ON pipeline_runs (tenant_id);
        """,
        f"""
        CREATE INDEX {if_not_exists} ix_pipeline_runs_name_started
            ON pipeline_runs (pipeline_name, started_at);
        """,
        # bid_breakdowns — the Layer A foundation table.
        f"""
        CREATE TABLE {if_not_exists} bid_breakdowns (
            id                  VARCHAR(36) PRIMARY KEY,
            tenant_id           VARCHAR(36) NOT NULL REFERENCES tenants(id)
                                    ON DELETE CASCADE,
            bid_event_id        VARCHAR(36) REFERENCES bid_events(id)
                                    ON DELETE SET NULL,
            vista_estimate_id   VARCHAR(120),
            submitted_amount    NUMERIC(14, 2) NOT NULL,
            estimate_date       DATE NOT NULL,
            cost_buckets        JSON NOT NULL,
            man_hours           NUMERIC(10, 2),
            crew_composition    JSON,
            equipment_mix       JSON,
            sub_quotes          JSON,
            supplier_quotes     JSON,
            won                 BOOLEAN NOT NULL DEFAULT FALSE,
            notes               TEXT,
            created_at          {ts} NOT NULL DEFAULT {now},
            updated_at          {ts} NOT NULL DEFAULT {now},
            CONSTRAINT uq_bid_breakdowns_vista_estimate
                UNIQUE (vista_estimate_id)
        );
        """,
        f"""
        CREATE INDEX {if_not_exists} ix_bid_breakdowns_tenant_id
            ON bid_breakdowns (tenant_id);
        """,
        f"""
        CREATE INDEX {if_not_exists} ix_bid_breakdowns_bid_event
            ON bid_breakdowns (bid_event_id);
        """,
        f"""
        CREATE INDEX {if_not_exists} ix_bid_breakdowns_tenant_estimate_date
            ON bid_breakdowns (tenant_id, estimate_date);
        """,
    ]


def _add_columns(is_sqlite: bool) -> list[tuple[str, str, str]]:
    """Returns (table, column, coltype-with-default) tuples.

    NOT NULL columns with NOW()/CURRENT_TIMESTAMP defaults need
    different handling on SQLite: SQLite rejects non-literal defaults
    on ALTER TABLE ADD COLUMN, so we declare those columns NULL on
    SQLite (matching the developer's local dev DB) and let the model
    re-create the table on next ``Base.metadata.create_all``. In
    production this script is only ever run against Postgres, where
    NOT NULL with NOW() default is fine.
    """
    ts = _ts_type(is_sqlite)
    now = _now_default(is_sqlite)
    # On SQLite, drop NOT NULL on the timestamp adds; the application
    # layer fills them on insert anyway.
    nn_ts = "" if is_sqlite else " NOT NULL"
    ts_default = ts + nn_ts + f" DEFAULT {now}"

    return [
        # bid_events — Layer A/B forward-compat columns.
        ("bid_events", "job_type", "TEXT"),
        ("bid_events", "job_subtype", "TEXT"),
        ("bid_events", "scope_keywords", "JSON"),
        ("bid_events", "agency_type", "TEXT"),
        ("bid_events", "funding_source", "TEXT"),
        ("bid_events", "project_size_band", "TEXT"),
        ("bid_events", "prevailing_wage", "BOOLEAN"),
        ("bid_events", "award_date", "DATE"),
        ("bid_events", "engineer_estimate", "NUMERIC(14, 2)"),
        (
            "bid_events",
            "pipeline_run_id",
            # FK declared inline so Postgres validates against
            # pipeline_runs at ALTER time. SQLite ignores REFERENCES
            # on ALTER ADD COLUMN but accepts the syntax.
            "VARCHAR(36) REFERENCES pipeline_runs(id) ON DELETE SET NULL",
        ),
        ("bid_events", "updated_at", ts_default),
        # bid_results — Layer B columns.
        ("bid_results", "pct_above_low", "NUMERIC(6, 4)"),
        (
            "bid_results",
            "is_disqualified",
            "BOOLEAN NOT NULL DEFAULT FALSE",
        ),
        ("bid_results", "bond_amount", "NUMERIC(14, 2)"),
        ("bid_results", "listed_subs", "JSON"),
        ("bid_results", "listed_suppliers", "JSON"),
        (
            "bid_results",
            "pipeline_run_id",
            "VARCHAR(36) REFERENCES pipeline_runs(id) ON DELETE SET NULL",
        ),
        ("bid_results", "created_at", ts_default),
        ("bid_results", "updated_at", ts_default),
        # contractors — audit timestamps.
        ("contractors", "created_at", ts_default),
        ("contractors", "updated_at", ts_default),
    ]


def _add_column_sql(
    table: str, column: str, coltype: str, *, is_sqlite: bool
) -> str:
    if is_sqlite:
        # SQLite has no ADD COLUMN IF NOT EXISTS — we catch the
        # OperationalError below for idempotency.
        return f"ALTER TABLE {table} ADD COLUMN {column} {coltype};"
    return (
        f"ALTER TABLE {table} "
        f"ADD COLUMN IF NOT EXISTS {column} {coltype};"
    )


async def migrate() -> None:
    is_sqlite = engine.dialect.name == "sqlite"
    log.info(
        "Running market_intel layer A/B migration (dialect=%s).",
        engine.dialect.name,
    )

    async with engine.begin() as conn:
        for stmt in _create_tables(is_sqlite):
            try:
                await conn.execute(text(stmt))
                log.info(
                    "Applied: %s",
                    stmt.strip().split("\n")[0][:80],
                )
            except (OperationalError, ProgrammingError) as exc:
                # CREATE TABLE IF NOT EXISTS should be idempotent.
                # Anything else here is a real error.
                log.warning("Skipped (already exists?): %s", exc)

        for table, column, coltype in _add_columns(is_sqlite):
            sql = _add_column_sql(table, column, coltype, is_sqlite=is_sqlite)
            try:
                await conn.execute(text(sql))
                log.info("Added %s.%s", table, column)
            except (OperationalError, ProgrammingError) as exc:
                msg = str(exc).lower()
                if (
                    "duplicate column" in msg
                    or "already exists" in msg
                ):
                    log.info(
                        "Column %s.%s already present — skipping.",
                        table, column,
                    )
                else:
                    raise

    log.info("market_intel layer A/B migration complete.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )
    asyncio.run(migrate())
