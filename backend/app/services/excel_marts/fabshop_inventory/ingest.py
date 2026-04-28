"""fabshop_inventory IngestJob — FabShopStockProducts.xlsx."""
from __future__ import annotations

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts.fabshop_inventory.schema import TABLE_NAME

job = register_job(
    IngestJob(
        name="fabshop_inventory",
        source_file="FabShopStockProducts.xlsx",
        target_table=TABLE_NAME,
        sheet_name="FabShopStockProducts",
        column_map={
            "Description": "description",
            "Price": "price",
        },
        type_map={"description": str, "price": int},
        dedupe_keys=["tenant_id", "description"],
    )
)
