"""Operator tool: fire the ITD bid-tab pipeline once.

Used by the Render cron service (see ``render.yaml`` ``fieldbridge-itd-pipeline``)
to schedule nightly runs in production. Also runnable by hand for a
one-shot sync:

    cd backend
    python scripts/run_itd_pipeline.py                        # default: ID
    python scripts/run_itd_pipeline.py --state ID --limit 5   # cap discovery

What it does:
  1. Open an async SQLAlchemy session against ``settings.database_url``.
  2. Construct an ``ITDPipeline`` with default fetcher.
  3. Call ``run_state(state, db)`` — discovers abstract URLs from the
     ITD index, fetches each via ``HttpFetcher`` (robots-aware,
     rate-limited), parses, idempotency-checks, writes
     ``BidEvent`` + ``BidResult`` rows under
     ``SHARED_NETWORK_TENANT_ID``.
  4. Log the counters dict and exit.

Exit codes:
  0 — pipeline ran cleanly (counters returned, no exception). May
      have skipped events for legitimate reasons (robots deny, legacy
      template, idempotent re-run); those are logged in the counters
      and are NOT failures.
  1 — pipeline raised. Render's cron service treats non-zero as a
      failed run and surfaces it in the dashboard. Inspect logs.

Why a wrapper script vs ``python -m``: same rationale as
``run_napc_probe.py`` and ``run_ingest.py`` — running a module under
``-m`` makes it ``__main__``, which breaks downstream imports that
expect ``app.services.market_intel.pipeline`` to be a normal module.
The wrapper imports it cleanly.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# sys.path bootstrap so ``app.*`` imports resolve when invoked as
# ``python scripts/run_itd_pipeline.py`` from the ``backend/`` directory.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.services.market_intel.pipeline import ITDPipeline  # noqa: E402

log = logging.getLogger("fieldbridge.itd_pipeline_cron")


async def _run(state: str, limit: int | None) -> int:
    async with AsyncSessionLocal() as db:
        kwargs = {"url_limit": limit} if limit is not None else {}
        async with ITDPipeline(**kwargs) as pipeline:
            counters = await pipeline.run_state(state, db)
    log.info("itd-pipeline counters: %s", counters)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the ITD bid-tab pipeline once.",
    )
    parser.add_argument(
        "--state",
        default="ID",
        help="State code (only 'ID' is supported in v1.5; UDOT/NDOT in v1.5b).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap URL discovery at N. Default: ITDPipeline.DEFAULT_URL_LIMIT.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    try:
        return asyncio.run(_run(args.state, args.limit))
    except Exception:
        log.exception("itd-pipeline run failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
