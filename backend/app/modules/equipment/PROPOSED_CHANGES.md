# Equipment Proposed Changes

## Mart Indexes For Equipment Status/List Performance

Large synthetic mart validation on 500 assets produced:

- `mart_equipment_utilization` list path via `/api/equipment/list?page_size=500`:
  `209.40ms`
- Status Board path over `mart_equipment_utilization`, `mart_work_orders`,
  `mart_equipment_transfers`, and `mart_asset_barcodes`: `902.40ms`

The list path exceeds the v1 target of 200ms, so Lead/schema owner should add
mart indexes rather than the Equipment Worker editing shared mart definitions
directly.

Recommended indexes:

```sql
CREATE INDEX IF NOT EXISTS ix_mart_equipment_utilization_tenant_truck_ticket_date
ON mart_equipment_utilization (tenant_id, truck, ticket_date);

CREATE INDEX IF NOT EXISTS ix_mart_equipment_rentals_tenant_equipment_picked_up
ON mart_equipment_rentals (tenant_id, equipment, picked_up_date);

CREATE INDEX IF NOT EXISTS ix_mart_asset_barcodes_tenant_barcode
ON mart_asset_barcodes (tenant_id, barcode);
```

Status Board would also benefit from these join/recency indexes:

```sql
CREATE INDEX IF NOT EXISTS ix_mart_work_orders_tenant_equipment_status_open
ON mart_work_orders (tenant_id, equipment, status, open_date);

CREATE INDEX IF NOT EXISTS ix_mart_equipment_transfers_tenant_tool_transfer
ON mart_equipment_transfers (tenant_id, tool_consumable, transfer_date);
```

All SQL references are mart table names only. No Vista SQL write path is
requested.
