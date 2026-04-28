"""asset_barcodes IngestJob — Barcodes.xlsx."""
from __future__ import annotations

from datetime import datetime

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts.asset_barcodes.schema import TABLE_NAME

job = register_job(
    IngestJob(
        name="asset_barcodes",
        source_file="Barcodes.xlsx",
        target_table=TABLE_NAME,
        sheet_name="Barcodes",
        column_map={
            "Barcode": "barcode",
            "Manufacturer": "manufacturer",
            "Material": "material",
            "Model": "model",
            "Retired Date": "retired_date",
        },
        type_map={
            "barcode": int,
            "manufacturer": str, "material": str, "model": str,
            "retired_date": datetime,
        },
        dedupe_keys=["tenant_id", "barcode"],
    )
)
