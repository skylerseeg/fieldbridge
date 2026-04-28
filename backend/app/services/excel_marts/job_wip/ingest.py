"""job_wip IngestJob — WIP report - Job Scheduling.xlsx."""
from __future__ import annotations

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts.job_wip.schema import TABLE_NAME

job = register_job(
    IngestJob(
        name="job_wip",
        source_file="WIP report - Job Scheduling.xlsx",
        target_table=TABLE_NAME,
        sheet_name="Job Scheduling",
        column_map={
            "Contract Job Description": "contract_job_description",
            "Total Contract": "total_contract",
            "Contract Cost TD": "contract_cost_td",
            "Est Cost to Complete": "est_cost_to_complete",
            "Est Total Cost": "est_total_cost",
            "Est Gross Profit": "est_gross_profit",
            "Est Gross Profit %": "est_gross_profit_pct",
            "Percent Complete": "percent_complete",
            "Gain (Fade) From Prior Mth": "gain_fade_from_prior_mth",
            "Billings To Date": "billings_to_date",
            "(Over) / Under Billings": "over_under_billings",
            "Contract Revenues Earned": "contract_revenues_earned",
            "Gross Profit (Loss) TD": "gross_profit_loss_td",
            "Gross Profit % TD": "gross_profit_pct_td",
        },
        type_map={
            "contract_job_description": str,
            "total_contract": float, "contract_cost_td": float,
            "est_cost_to_complete": float, "est_total_cost": float,
            "est_gross_profit": float, "est_gross_profit_pct": float,
            "percent_complete": float, "gain_fade_from_prior_mth": float,
            "billings_to_date": float, "over_under_billings": float,
            "contract_revenues_earned": float,
            "gross_profit_loss_td": float, "gross_profit_pct_td": float,
        },
        dedupe_keys=["tenant_id", "contract_job_description"],
    )
)
