"""proposals IngestJob — Proposal Bids.xlsx (2-row sample, thin schema)."""
from __future__ import annotations

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts.proposals.schema import TABLE_NAME

job = register_job(
    IngestJob(
        name="proposals",
        source_file="Proposal Bids.xlsx",
        target_table=TABLE_NAME,
        sheet_name="Proposal Bids",
        column_map={
            "Job": "job",
            "Owner": "owner",
            "Bid Type": "bid_type",
            "County": "county",
        },
        type_map={"job": str, "owner": str, "bid_type": str, "county": str},
        dedupe_keys=["tenant_id", "job", "owner", "bid_type"],
    )
)
