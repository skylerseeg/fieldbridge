"""bids_outlook IngestJob — Bid Outlook.xlsx.

Source header 'Man-datory' (with hyphen) normalizes to 'mandatory'.
"""
from __future__ import annotations

from datetime import datetime

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts.bids_outlook.schema import TABLE_NAME

job = register_job(
    IngestJob(
        name="bids_outlook",
        source_file="Bid Outlook.xlsx",
        target_table=TABLE_NAME,
        sheet_name="Bid Outlook",
        column_map={
            "Job": "job",
            "Need Plans": "need_plans",
            "Bid Bond": "bid_bond",
            "PQ": "pq",
            "SD": "sd",
            "CM GC": "cm_gc",
            "Plan Source": "plan_source",
            "Delivery Type": "delivery_type",
            "Public Opening": "public_opening",
            "Owner": "owner",
            "Completion Date": "completion_date",
            "Engineer Estimate": "engineer_estimate",
            "Ready For Review": "ready_for_review",
            "Estimator Time Off": "estimator_time_off",
            "Estimator Name": "estimator_name",
            "Bid Date": "bid_date",
            "Anticipated Bid Date": "anticipated_bid_date",
            "Pre Bid Date": "pre_bid_date",
            "Pre-Bid Competitors": "pre_bid_competitors",
            "Man-datory": "mandatory",
            "Person Going": "person_going",
            "Bid Type": "bid_type",
            "Labor Fade/Gain": "labor_fade_gain",
            "Costs Fade/Gain": "costs_fade_gain",
            "D.B. Wages": "db_wages",
            "AIS": "ais",
            "Notes": "notes",
        },
        type_map={
            "job": str, "owner": str, "bid_type": str,
            "need_plans": bool, "bid_bond": str,
            "pq": bool, "sd": bool, "cm_gc": bool,
            "plan_source": str, "delivery_type": str,
            "public_opening": bool,
            "completion_date": datetime,
            "engineer_estimate": str,
            "ready_for_review": bool,
            "estimator_time_off": str, "estimator_name": str,
            "bid_date": datetime,
            "anticipated_bid_date": datetime,
            "pre_bid_date": datetime,
            "pre_bid_competitors": str,
            "mandatory": bool, "person_going": str,
            "labor_fade_gain": int, "costs_fade_gain": int,
            "db_wages": bool, "ais": bool, "notes": str,
        },
        dedupe_keys=["tenant_id", "job", "owner", "bid_type"],
    )
)
