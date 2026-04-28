"""bids_history IngestJob — All Bid History.xlsx."""
from __future__ import annotations

from datetime import datetime

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts.bids_history.schema import TABLE_NAME


def _column_map() -> dict[str, str]:
    m: dict[str, str] = {
        "Was Bid": "was_bid",
        "Heavy Bid #": "heavy_bid_number",
        "Job": "job",
        "Owner": "owner",
        "Bid Type": "bid_type",
        "County": "county",
        "Estimator": "estimator",
        "Bid Date": "bid_date",
        "Completion Date": "completion_date",
        "Labor % Cost Factor": "labor_cost_factor",
        "Avg Mark Up %": "avg_mark_up_pct",
        "Mark Up": "mark_up",
        "Overhead Add On": "overhead_add_on",
        "Equip OP Exp": "equip_op_exp",
        "CO Equip": "co_equip",
        "High": "high",
        "Low": "low",
        "VanCon": "vancon",
        "Rank": "rank",
        "Won": "won",
        "Lost By": "lost_by",
        "% Over": "percent_over",
        "Number Bidders": "number_bidders",
        "Bids": "bids",
        "PQ": "pq",
        "Plan Source": "plan_source",
        "D.B. Wages": "db_wages",
        "Engineer Estimate": "engineer_estimate",
        "Notice To Proceed Date": "notice_to_proceed_date",
        "Competitor Ids": "competitor_ids",
        "Deep": "deep",
        "Traffic Control": "traffic_control",
        "Dewatering": "dewatering",
        "Bypass Pumping": "bypass_pumping",
        "Tight Time Frame": "tight_time_frame",
        "Tight Job Site": "tight_job_site",
        "Haul Off": "haul_off",
        "Insurance Requirement": "insurance_requirement",
    }
    for i in range(1, 18):
        m[f"Bid {i} Comp"] = f"bid_{i}_comp"
        m[f"Bid {i} Amt"] = f"bid_{i}_amt"
        m[f"Bid {i} Won"] = f"bid_{i}_won"
    return m


def _type_map() -> dict[str, type]:
    t: dict[str, type] = {
        "was_bid": bool, "heavy_bid_number": int,
        "job": str, "owner": str, "bid_type": str, "county": str,
        "estimator": str,
        "bid_date": datetime, "completion_date": datetime,
        "notice_to_proceed_date": datetime,
        "labor_cost_factor": float, "avg_mark_up_pct": float,
        "mark_up": float, "overhead_add_on": float, "equip_op_exp": float,
        "co_equip": float, "high": float, "low": float, "vancon": float,
        "rank": float, "won": float, "lost_by": float, "percent_over": float,
        "number_bidders": float, "bids": str,
        "pq": bool, "plan_source": str, "db_wages": bool,
        "engineer_estimate": str, "competitor_ids": str,
        "deep": float, "traffic_control": float, "dewatering": float,
        "bypass_pumping": float, "tight_time_frame": float,
        "tight_job_site": float, "haul_off": float,
        "insurance_requirement": float,
    }
    for i in range(1, 18):
        t[f"bid_{i}_comp"] = str
        t[f"bid_{i}_amt"] = float
        t[f"bid_{i}_won"] = float
    return t


job = register_job(
    IngestJob(
        name="bids_history",
        source_file="All Bid History.xlsx",
        target_table=TABLE_NAME,
        sheet_name="All Bid History",
        column_map=_column_map(),
        type_map=_type_map(),
        dedupe_keys=["tenant_id", "job", "bid_date"],
    )
)
