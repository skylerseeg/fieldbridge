"""SQL templates for Market Intel read endpoints.

Each ``*.sql`` file in this directory is a parameterized SQL query
loaded by ``app.modules.market_intel.service``. The split here is:

  * **SQL** does the filter + the cross-table join (bid_events ↔
    bid_results ↔ per-event low-bidder amount). Tenant scoping
    happens in the WHERE clause as
    ``tenant_id IN (:caller_tenant, :shared_network_tenant)``.
  * **Python** does the GROUP BY + non-portable aggregates (median,
    quarter truncation). This keeps queries cross-dialect — SQLite
    in tests, Postgres in prod — without ``percentile_cont`` /
    ``date_trunc`` conditionals.

Call ``load_sql("competitor_curves")`` to read a template.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_SQL_DIR = Path(__file__).parent


@lru_cache(maxsize=8)
def load_sql(name: str) -> str:
    """Read ``{name}.sql`` from this directory. Cached for repeat calls.

    Raises ``FileNotFoundError`` if the template is missing — the
    service module bootstraps each query at import time so
    misspellings fail fast.
    """
    path = _SQL_DIR / f"{name}.sql"
    return path.read_text(encoding="utf-8")
