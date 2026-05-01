"""equipment_fuel IngestJob — Material analytics Fuel Totals.xlsx."""
from __future__ import annotations

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts.equipment_fuel.schema import TABLE_NAME

job = register_job(
    IngestJob(
        name="equipment_fuel",
        source_file="Material analytics Fuel Totals.xlsx",
        target_table=TABLE_NAME,
        sheet_name="Fuel Totals",
        column_map={
            "Job": "job",
            "Job Type": "job_type",
            "Material (Tons)": "material_tons",
            "Concrete (Yards)": "concrete_yards",
            "Flowfill (Yards)": "flowfill_yards",
        },
        type_map={
            "job": str, "job_type": str,
            "material_tons": float,
            "concrete_yards": int, "flowfill_yards": int,
        },
        dedupe_keys=["tenant_id", "job", "job_type"],
    )
)
