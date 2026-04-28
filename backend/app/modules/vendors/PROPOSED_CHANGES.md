# Proposed Changes — Vendors Supplier Enrichment

Date: 2026-04-27

## Summary

Add a vendor-owned enrichment overlay table so v1 can accept contact, CSI, and firm-type corrections without writing back to `mart_vendors` or Vista `apvend`.

## New Mart Table

Table: `mart_vendor_enrichments`

```sql
CREATE TABLE mart_vendor_enrichments (
    tenant_id VARCHAR(36) NOT NULL,
    vendor_id VARCHAR(255) NOT NULL,
    contact VARCHAR(200),
    title VARCHAR(120),
    email VARCHAR(200),
    phone VARCHAR(40),
    firm_type VARCHAR(120),
    code_1 VARCHAR(80),
    code_2 VARCHAR(80),
    code_3 VARCHAR(80),
    code_4 VARCHAR(80),
    code_5 VARCHAR(80),
    notes TEXT,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (tenant_id, vendor_id)
);
```

Recommended indexes:

```sql
CREATE INDEX ix_mart_vendor_enrichments_tenant_id
    ON mart_vendor_enrichments (tenant_id);
```

## Migration Intent

1. Create `mart_vendor_enrichments`.
2. Do not backfill rows. It is an overlay table populated only by the new vendors enrichment endpoint.
3. Keep `mart_vendors` as the read-only source-of-truth import from `Firm Contacts.xlsx` / future Vista `apvend`.
4. Read paths use `mart_vendors LEFT JOIN mart_vendor_enrichments` at service time, with non-empty enrichment values winning over `mart_vendors` values.

## API Contract

`POST /api/vendors/enrichments/{vendor_id:path}`

Request body:

```json
{
  "contact": "Jane Buyer",
  "title": "Estimator",
  "email": "jane@example.com",
  "phone": "555-0123",
  "firm_type": "supplier",
  "codes": ["0330-Cast-in-place Concrete", "0350-Precast"],
  "notes": "Confirmed by procurement."
}
```

Response body: merged `VendorDetail`.

## Behavior

- Validate that `{vendor_id}` exists in `mart_vendors` for the current tenant before writing.
- Upsert one row per `(tenant_id, vendor_id)` into `mart_vendor_enrichments`.
- Reject empty payloads.
- Trim and dedupe `codes`, keeping a maximum of five.
- Summary, list, detail, insights, and recommendations all read the merged view.
- Once an enrichment adds email or phone to a `minimal` row, `mart_vendors LEFT JOIN mart_vendor_enrichments` should classify it as `partial` or `complete`, and minimal-contact recommendations should fall out of the recommendation context.
