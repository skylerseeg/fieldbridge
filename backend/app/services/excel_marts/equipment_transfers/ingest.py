"""equipment_transfers IngestJob — Transfer Records.xlsx."""
from __future__ import annotations

from datetime import datetime

from app.core.ingest import IngestJob, register_job
from app.services.excel_marts.equipment_transfers.schema import TABLE_NAME

job = register_job(
    IngestJob(
        name="equipment_transfers",
        source_file="Transfer Records.xlsx",
        target_table=TABLE_NAME,
        sheet_name="Transfer Records",
        column_map={
            "Id": "id",
            "Transfer Date": "transfer_date",
            "Tool/Consumable": "tool_consumable",
            "Location": "location",
            "Quantity": "quantity",
            "Total Price": "total_price",
            "Requested By": "requested_by",
            "User": "user",
        },
        type_map={
            "id": int, "transfer_date": datetime,
            "tool_consumable": str, "location": str,
            "quantity": int, "total_price": float,
            "requested_by": str, "user": str,
        },
        dedupe_keys=["tenant_id", "id"],
    )
)
