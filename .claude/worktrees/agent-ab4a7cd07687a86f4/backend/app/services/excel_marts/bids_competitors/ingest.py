"""bids_competitors IngestJob — Competitor Bids.xlsx.

Source had 0 data rows at introspection. Types below are the *intended*
schema once data arrives — pandas inferred all-str with no data to sample.
Schema is ready; next export will populate it.
"""
from __future__ import annotations

from datetime import datetime

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts.bids_competitors.schema import TABLE_NAME

job = register_job(
    IngestJob(
        name="bids_competitors",
        source_file="Competitor Bids.xlsx",
        target_table=TABLE_NAME,
        sheet_name="Competitor Bids",
        column_map={
            "Job": "job",
            "Bid Type": "bid_type",
            "Heavy Bid #": "heavy_bid_number",
            "Bid Date": "bid_date",
            "Bid Amount": "bid_amount",
            "Rank": "rank",
            "Won": "won",
            "# Bidders": "num_bidders",
            "Low": "low",
            "High": "high",
            "VanCon": "vancon",
            "Lower Than VanCon": "lower_than_vancon",
        },
        type_map={
            "job": str, "bid_type": str, "heavy_bid_number": str,
            "bid_date": datetime,
            "bid_amount": float, "rank": int, "won": str,
            "num_bidders": int, "low": float, "high": float,
            "vancon": float, "lower_than_vancon": float,
        },
        dedupe_keys=["tenant_id", "job", "heavy_bid_number", "bid_date"],
    )
)
