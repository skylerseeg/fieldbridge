"""Populate ``mart_predictive_maintenance`` from Vista ``emem``.

Usage:
    python -m scripts.run_pm_overdue                       # all active tenants
    python -m scripts.run_pm_overdue --tenant vancon       # one tenant
    python -m scripts.run_pm_overdue --tenant vancon \\
            --fixture path/to/emem_sample.json             # offline test path

The fixture flag bypasses Vista and reads a JSON list shaped like
``emem`` rows. Useful in dev environments where ``vista_sql_*`` isn't
configured — lets you verify the writer + the page render end-to-end
without a live Vista connection.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Make the backend package importable when run as a script.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.ingest import _sync_url
from app.models.tenant import Tenant
from app.services.predictive_maintenance import write_pm_overdue


log = logging.getLogger("scripts.run_pm_overdue")


def _load_tenants(session: Session, slug: str | None) -> list[Tenant]:
    stmt = select(Tenant)
    if slug:
        stmt = stmt.where(Tenant.slug == slug)
    return list(session.execute(stmt).scalars().all())


def _load_emem_for_tenant(tenant: Tenant) -> list[dict]:
    """Pull emem rows for a tenant. Returns [] if Vista isn't configured."""
    try:
        from app.services import vista_sync
        return vista_sync.get_equipment(tenant=tenant)
    except Exception as exc:  # noqa: BLE001
        log.warning("Vista emem fetch failed for tenant=%s: %s", tenant.slug, exc)
        return []


def _load_fixture(path: Path) -> list[dict]:
    with path.open() as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Fixture {path} must be a JSON array of emem-shaped objects.")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", help="Tenant slug. Default: every active tenant.")
    parser.add_argument(
        "--fixture",
        type=Path,
        help="Read equipment master from a JSON file instead of Vista.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.fixture and not args.tenant:
        parser.error("--fixture requires --tenant")

    engine = create_engine(_sync_url(settings.database_url), pool_pre_ping=True)
    SessionLocal = sessionmaker(engine, expire_on_commit=False)

    fixture_rows: list[dict] | None = None
    if args.fixture:
        fixture_rows = _load_fixture(args.fixture)
        log.info("Loaded %d emem rows from fixture %s", len(fixture_rows), args.fixture)

    with SessionLocal() as session:
        tenants = _load_tenants(session, args.tenant)

    if not tenants:
        log.error("No tenants matched (slug=%r).", args.tenant)
        return 2

    exit_code = 0
    for tenant in tenants:
        emem = fixture_rows if fixture_rows is not None else _load_emem_for_tenant(tenant)
        if not emem:
            log.warning(
                "tenant=%s: no equipment master rows available "
                "(Vista offline? pass --fixture for a dry run).",
                tenant.slug,
            )
            exit_code = max(exit_code, 1)
            continue

        result = write_pm_overdue(engine, tenant.id, emem)
        log.info(
            "tenant=%s seen=%d inserted=%d updated=%d auto_dismissed=%d skipped=%d",
            tenant.slug,
            result.equipment_seen,
            result.rows_inserted,
            result.rows_updated,
            result.rows_auto_dismissed,
            result.skipped_no_pm_schedule,
        )
        if result.errors:
            for err in result.errors:
                log.error("tenant=%s: %s", tenant.slug, err)
            exit_code = max(exit_code, 1)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
