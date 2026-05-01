"""estimates IngestJob — Estimates.xlsx → mart_estimates."""
from __future__ import annotations

from datetime import datetime

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts.estimates.schema import TABLE_NAME

job = register_job(
    IngestJob(
        name="estimates",
        source_file="Estimates.xlsx",
        target_table=TABLE_NAME,
        sheet_name="Estimates",
        column_map={
            "Code": "code",
            "Name": "name",
            "Date Created": "date_created",
            "Estimate Total Cost": "estimate_total_cost",
            "Actual Bid Markup": "actual_bid_markup",
            "Actual Markup Takeoff": "actual_markup_takeoff",
            "Addon Bond Total": "addon_bond_total",
            "Addon Cost": "addon_cost",
            "Bond Total": "bond_total",
            "Addon Markup": "addon_markup",
            "Bid Date": "bid_date",
            "Bid Total": "bid_total",
            "Overhead %": "overhead_pct",
        },
        type_map={
            "code": str, "name": str,
            "date_created": datetime, "bid_date": datetime,
            "estimate_total_cost": float, "actual_bid_markup": float,
            "actual_markup_takeoff": float, "addon_bond_total": float,
            "addon_cost": float, "bond_total": float,
            "addon_markup": int, "bid_total": float, "overhead_pct": float,
        },
        dedupe_keys=["tenant_id", "code"],
    )
)
