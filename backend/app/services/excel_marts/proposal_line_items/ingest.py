"""proposal_line_items IngestJob — Proposal Bid Details.xlsx.

Only 1 data row sampled; reference/PM/Super columns inferred as float
(all-null) in the snapshot, but we declare them as str because the other
non-null row shows string data. Coercion will no-op on the nulls.
"""
from __future__ import annotations

from datetime import datetime

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts.proposal_line_items.schema import TABLE_NAME

job = register_job(
    IngestJob(
        name="proposal_line_items",
        source_file="Proposal Bid Details.xlsx",
        target_table=TABLE_NAME,
        sheet_name="Proposal Bid Details",
        column_map={
            "Competitor": "competitor",
            "Design Fee": "design_fee",
            "CM Fee": "cm_fee",
            "CM Monthly Fee": "cm_monthly_fee",
            "Contractor OHP Fee": "contractor_ohp_fee",
            "Contractor Bonds/Ins": "contractor_bonds_ins",
            "Contractor CO Markup": "contractor_co_markup",
            "City Budget": "city_budget",
            "Contractor Start": "contractor_start",
            "Contractor Days": "contractor_days",
            "Contractor Projects": "contractor_projects",
            "PM Projects": "pm_projects",
            "Contractor PM": "contractor_pm",
            "Contractor Super": "contractor_super",
            "Reference 1": "reference_1",
            "Reference 2": "reference_2",
            "Reference 3": "reference_3",
        },
        type_map={
            "competitor": str,
            "design_fee": int, "cm_fee": int, "cm_monthly_fee": int,
            "contractor_ohp_fee": int, "contractor_bonds_ins": int,
            "contractor_co_markup": int, "city_budget": int,
            "contractor_start": datetime,
            "contractor_days": int, "contractor_projects": int,
            "pm_projects": int,
            "contractor_pm": str, "contractor_super": str,
            "reference_1": str, "reference_2": str, "reference_3": str,
        },
        dedupe_keys=["tenant_id", "_row_hash"],
    )
)
