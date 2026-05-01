"""Excel-backed data marts.

Each submodule follows the pattern: schema.py / ingest.py / __init__.py.
Importing this package triggers ``register_job()`` side-effects in every mart's
ingest.py, populating ``app.core.ingest.JOB_REGISTRY``.

See README.md and ``fieldbridge/docs/data_mapping.md`` for conventions.
"""
from __future__ import annotations

# P0 — revenue-critical marts (graduate to Vista v2 first)
from app.services.excel_marts import equipment_utilization  # noqa: F401
from app.services.excel_marts import vendors  # noqa: F401

# P1 — high-value job/equipment/estimate marts
from app.services.excel_marts import estimates  # noqa: F401
from app.services.excel_marts import estimate_variance  # noqa: F401
from app.services.excel_marts import employee_assets  # noqa: F401
from app.services.excel_marts import equipment_rentals  # noqa: F401
from app.services.excel_marts import equipment_fuel  # noqa: F401
from app.services.excel_marts import job_schedule  # noqa: F401
from app.services.excel_marts import job_wip  # noqa: F401

# P2 — bids / proposals / FTE planning
from app.services.excel_marts import bids_history  # noqa: F401
from app.services.excel_marts import bids_outlook  # noqa: F401
from app.services.excel_marts import proposals  # noqa: F401
from app.services.excel_marts import proposal_line_items  # noqa: F401
from app.services.excel_marts import bids_competitors  # noqa: F401
from app.services.excel_marts import hcss_activities  # noqa: F401
from app.services.excel_marts import equipment_transfers  # noqa: F401
from app.services.excel_marts import hours_projected  # noqa: F401
from app.services.excel_marts import fte_class_actual  # noqa: F401
from app.services.excel_marts import fte_class_projected  # noqa: F401
from app.services.excel_marts import fte_type_actual  # noqa: F401
from app.services.excel_marts import fte_overhead_actual  # noqa: F401
from app.services.excel_marts import fte_overhead_projected  # noqa: F401
from app.services.excel_marts import productivity  # noqa: F401

# P3 — reference/legacy marts
from app.services.excel_marts import bids_history_legacy  # noqa: F401
from app.services.excel_marts import asset_barcodes  # noqa: F401
from app.services.excel_marts import fabshop_inventory  # noqa: F401

# Vista-only marts — no Excel ingest, Table registered for create_all().
# NOT included in MART_MODULES because list_marts() describes ingest jobs
# and these don't have one yet.
from app.services.excel_marts import work_orders  # noqa: F401
from app.services.excel_marts import predictive_maintenance  # noqa: F401
from app.services.excel_marts import vendor_enrichments  # noqa: F401


MART_MODULES = (
    # P0
    equipment_utilization,
    vendors,
    # P1
    estimates,
    estimate_variance,
    employee_assets,
    equipment_rentals,
    equipment_fuel,
    job_schedule,
    job_wip,
    # P2
    bids_history,
    bids_outlook,
    proposals,
    proposal_line_items,
    bids_competitors,
    hcss_activities,
    equipment_transfers,
    hours_projected,
    fte_class_actual,
    fte_class_projected,
    fte_type_actual,
    fte_overhead_actual,
    fte_overhead_projected,
    # P3
    bids_history_legacy,
    asset_barcodes,
    fabshop_inventory,
)


def list_marts() -> list[dict]:
    """Return a lightweight descriptor for every registered mart.

    Used by ``scripts/create_mart_tables.py`` and the ingest report writer.
    """
    out: list[dict] = []
    for mod in MART_MODULES:
        job = getattr(mod, "job", None)
        table_name = getattr(mod, "TABLE_NAME", None)
        out.append(
            {
                "module": mod.__name__.rsplit(".", 1)[-1],
                "table": table_name,
                "source_file": getattr(job, "source_file", None),
                "sheet_name": getattr(job, "sheet_name", None),
                "dedupe_keys": list(getattr(job, "dedupe_keys", []) or []),
            }
        )
    return out


__all__ = ["MART_MODULES", "list_marts"]
