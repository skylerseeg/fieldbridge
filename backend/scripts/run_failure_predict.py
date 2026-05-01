"""Populate ``mart_predictive_maintenance`` via the AI failure-prediction agent.

Usage:
    python -m scripts.run_failure_predict --tenant vancon
    python -m scripts.run_failure_predict --tenant vancon \\
            --fixture-emem tests/fixtures/pm_overdue/emem_sample.json \\
            --fixture-emwo tests/fixtures/failure_predict/emwo_sample.json
    python -m scripts.run_failure_predict --tenant vancon \\
            --mock-alerts tests/fixtures/failure_predict/agent_alerts_sample.json

Pulls Vista ``emem`` + ``emwo`` for the tenant by default. The
``--fixture-*`` flags substitute JSON files for either or both inputs;
``--mock-alerts`` skips the live Claude call entirely and feeds the
mart from a canned agent-output file (useful for offline UI testing
without spending tokens).

Per-tenant invocation only — failure-prediction is gated by explicit
opt-in during shakedown.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.ingest import _sync_url
from app.models.tenant import Tenant
from app.services.predictive_maintenance import write_failure_predictions


log = logging.getLogger("scripts.run_failure_predict")


def _load_tenant(session: Session, slug: str) -> Tenant | None:
    return session.execute(
        select(Tenant).where(Tenant.slug == slug)
    ).scalar_one_or_none()


def _load_emem(tenant: Tenant, fixture: Path | None) -> list[dict]:
    if fixture is not None:
        return _read_json_list(fixture)
    try:
        from app.services import vista_sync
        return vista_sync.get_equipment(tenant=tenant)
    except Exception as exc:  # noqa: BLE001
        log.warning("Vista emem fetch failed: %s", exc)
        return []


def _load_emwo(tenant: Tenant, fixture: Path | None) -> list[dict]:
    if fixture is not None:
        return _read_json_list(fixture)
    try:
        from app.services import vista_sync
        return vista_sync.get_work_orders(tenant=tenant)
    except Exception as exc:  # noqa: BLE001
        log.warning("Vista emwo fetch failed: %s", exc)
        return []


def _read_json_list(path: Path) -> list[dict]:
    with path.open() as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON array.")
    return data


def _mock_agent_call(alerts_by_equipment: dict[str, list[dict]]):
    """Build an agent_call shim that returns canned alerts per equipment."""
    def _call(equipment_history, pm_schedule):
        eq_id = (pm_schedule[0].get("Equipment") if pm_schedule else None) or ""
        return alerts_by_equipment.get(eq_id, []), None
    return _call


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True, help="Tenant slug.")
    parser.add_argument("--fixture-emem", type=Path)
    parser.add_argument("--fixture-emwo", type=Path)
    parser.add_argument(
        "--mock-alerts",
        type=Path,
        help="Skip the Claude call. JSON object mapping equipment_id -> [alert, …].",
    )
    parser.add_argument(
        "--max-equipment",
        type=int,
        help="Cap how many equipment we analyze this run (smoke testing).",
    )
    parser.add_argument("--min-wo-history", type=int, default=2)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    engine = create_engine(_sync_url(settings.database_url), pool_pre_ping=True)
    SessionLocal = sessionmaker(engine, expire_on_commit=False)

    with SessionLocal() as session:
        tenant = _load_tenant(session, args.tenant)
    if tenant is None:
        log.error("No tenant with slug=%r", args.tenant)
        return 2

    emem = _load_emem(tenant, args.fixture_emem)
    emwo = _load_emwo(tenant, args.fixture_emwo)
    if not emem:
        log.error("No equipment master rows available; aborting.")
        return 1
    if not emwo:
        log.warning("No work orders available — agent will skip every equipment.")

    agent_call = None
    if args.mock_alerts is not None:
        with args.mock_alerts.open() as f:
            mock = json.load(f)
        if not isinstance(mock, dict):
            log.error("--mock-alerts must be a JSON object mapping equipment -> alerts.")
            return 1
        agent_call = _mock_agent_call(mock)
        log.info("Mock agent active — %d equipment IDs canned.", len(mock))

    result = write_failure_predictions(
        engine,
        tenant.id,
        emem,
        emwo,
        min_wo_history=args.min_wo_history,
        max_equipment=args.max_equipment,
        agent_call=agent_call,
    )

    log.info(
        "tenant=%s seen=%d analyzed=%d skipped=%d inserted=%d updated=%d unmappable=%d cost=$%.4f",
        tenant.slug,
        result.equipment_seen,
        result.equipment_analyzed,
        result.equipment_skipped_no_history,
        result.rows_inserted,
        result.rows_updated,
        result.alerts_unmappable,
        result.total_cost_usd,
    )
    if result.errors:
        for err in result.errors:
            log.error("tenant=%s: %s", tenant.slug, err)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
