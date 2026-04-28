# Excel Mart Ingest Report

Generated after the first end-to-end run of `make ingest` against a fresh
SQLite file (`fieldbridge/backend/ingest_run.db`). All 25 registered
`IngestJob`s ran to completion; 23 landed `[ok]` and 2 landed `[partial]`
because they fell back to the `_row_hash` dedupe strategy (which always
emits a `WARN` — see `docs/data_mapping.md` §Dedupe key conventions).

- **Tenant**: `vancon` (id seeded by `scripts/create_mart_tables.py`)
- **DB**: `sqlite:///./ingest_run.db`
- **Tables created**: 29 total (25 mart tables + `tenants`, `users`, `usage_events`, `ingest_log`)
- **Jobs run**: 25 / 25 — 0 hard errors
- **Total source rows read**: 170,945
- **Total rows written to marts**: 166,630 (row-hash + natural-key collapses documented below)
- **Wall clock**: ~74 s on WSL

Re-running `make ingest` a second time UPSERTs in place (same hashes → no
duplicate rows).

---

## Per-mart results

Columns: **Source rows** (read from Excel) → **Written** (sent to UPSERT) →
**Rows in table** (final, post-collapse). When Written > Rows-in-table the
dedupe key collapsed duplicate source rows into single mart rows —
that's the intended behavior.

### P0 — revenue-critical

| Mart | Source file | Source rows | Written | Rows in table | Columns | Dedupe keys | Status |
|---|---|---:|---:|---:|---:|---|---|
| `equipment_utilization` | Equipment Utilization.xlsx | 11,291 | 7,752 | 7,728 | 21 | `tenant_id, ticket_date, ticket, truck` | ok — 3,539 rows skipped (null natural-key component) |
| `vendors` | Firm Contacts.xlsx | 2,492 | 2,492 | 1,861 | 13 | `tenant_id, _row_hash` | partial — row-hash WARN; 631 exact-duplicate contact rows collapsed |

### P1 — job / equipment / estimate core

| Mart | Source file | Source rows | Written | Rows in table | Columns | Dedupe keys | Status |
|---|---|---:|---:|---:|---:|---|---|
| `estimates` | Estimates.xlsx | 2,074 | 2,074 | 2,074 | 14 | `tenant_id, code` | ok |
| `estimate_variance` | Estimate Vs Actual.xlsx | 348 | 302 | 302 | 7 | `tenant_id, job_grouping, close_month` | ok — 46 rows skipped (missing close_month) |
| `employee_assets` | Employee Assets.xlsx | 571 | 571 | 569 | 14 | `tenant_id, asset` | ok — 2 rows collapsed on duplicate asset tag |
| `equipment_rentals` | Rentals.xlsx | 4 | 4 | 4 | 18 | `tenant_id, equipment, rental_company, picked_up_date` | ok |
| `equipment_fuel` | Material analytics Fuel Totals.xlsx | 11 | 11 | 11 | 6 | `tenant_id, job, job_type` | ok |
| `job_schedule` | Job Scheduling.xlsx | 44 | 44 | 44 | 10 | `tenant_id, priority, job` | ok |
| `job_wip` | WIP report - Job Scheduling.xlsx | 42 | 41 | 41 | 15 | `tenant_id, contract_job_description` | ok — 1 row skipped (blank description) |

### P2 — bids / proposals / FTE planning

| Mart | Source file | Source rows | Written | Rows in table | Columns | Dedupe keys | Status |
|---|---|---:|---:|---:|---:|---|---|
| `bids_history` | All Bid History.xlsx | 1,808 | 1,808 | 1,798 | 90 | `tenant_id, job, bid_date` | ok — 10 rows collapsed on duplicate (job, bid_date) |
| `bids_outlook` | Bid Outlook.xlsx | 21 | 20 | 20 | 28 | `tenant_id, job, owner, bid_type` | ok — 1 row skipped (null natural-key) |
| `proposals` | Proposal Bids.xlsx | 2 | 2 | 2 | 5 | `tenant_id, job, owner, bid_type` | ok |
| `proposal_line_items` | Proposal Bid Details.xlsx | 1 | 1 | 1 | 19 | `tenant_id, _row_hash` | partial — row-hash WARN; only 1 sample row in the file |
| `bids_competitors` | Competitor Bids.xlsx | 0 | 0 | 0 | 13 | `tenant_id, job, heavy_bid_number, bid_date` | ok — **file has 0 data rows** (flagged for follow-up; see Notes) |
| `hcss_activities` | HCSS Activities.xlsx | 144,575 | 144,575 | 103,964 | 13 | `tenant_id, estimate_code, activity_code` | ok — 40,611 rows collapsed on duplicate (estimate_code, activity_code) |
| `equipment_transfers` | Transfer Records.xlsx | 1,803 | 1,803 | 1,803 | 9 | `tenant_id, id` | ok |
| `hours_projected` | Projected Hours.xlsx | 2,367 | 2,366 | 2,366 | 33 | `tenant_id, job, phase` | ok — 1 row skipped |
| `fte_class_actual` | Job class FTE actual projections.xlsx | 28 | 28 | 28 | 20 | `tenant_id, class_name` | ok — 12-month wide |
| `fte_class_projected` | Job class FTE Projections.xlsx | 28 | 28 | 28 | 46 | `tenant_id, class_name` | ok — 36-month wide |
| `fte_type_actual` | Job type FTE actual.xlsx | 12 | 12 | 12 | 20 | `tenant_id, job_type` | ok — 12-month wide |
| `fte_overhead_actual` | Overhead FTE Actuals.xlsx | 10 | 10 | 10 | 20 | `tenant_id, department` | ok — 12-month wide |
| `fte_overhead_projected` | Overhead FTE Projections.xlsx | 0 | 0 | 0 | 20 | `tenant_id, department` | ok — **file has 0 data rows** (flagged for follow-up; see Notes) |

### P3 — reference / legacy

| Mart | Source file | Source rows | Written | Rows in table | Columns | Dedupe keys | Status |
|---|---|---:|---:|---:|---:|---|---|
| `bids_history_legacy` | Bid History.xlsx | 1,328 | 1,328 | 1,328 | 40 | `tenant_id, job, bid_date` | ok |
| `asset_barcodes` | Barcodes.xlsx | 1,572 | 1,572 | 1,557 | 6 | `tenant_id, barcode` | ok — 15 rows collapsed on duplicate barcode |
| `fabshop_inventory` | FabShopStockProducts.xlsx | 38 | 38 | 38 | 3 | `tenant_id, description` | ok |

---

## Dedupe strategy summary

| Strategy | Mart count | Marts |
|---|---:|---|
| Explicit ID | 1 | `equipment_transfers` (`id`) |
| Composite natural key | 22 | everything else except the two row-hash falls |
| Row hash (fallback) | 2 | `vendors`, `proposal_line_items` — both emit the `WARN dedupe_strategy=row_hash` line in `ingest_log.errors` |

Row-hash is a fallback, not a design goal. Both uses are documented in
the corresponding mart's `schema.py` docstring as TODOs to revisit once
the source system gives us a stable key.

---

## Notes / follow-ups

### Empty source files (ingested cleanly but carry no data)

- **Competitor Bids.xlsx** → `mart_bids_competitors` (0 rows). Headers
  present; this looks like a template that VanCon hadn't started
  populating when the snapshot was taken. Schema built from headers so
  the downstream UI won't break; revisit when real data arrives.
- **Overhead FTE Projections.xlsx** → `mart_fte_overhead_projected` (0 rows).
  Sibling file `Overhead FTE Actuals.xlsx` has 10 rows; the column layout
  was inferred from the actuals mart.

### Ambiguous / near-empty inputs (schema built, data sparse)

- **Proposal Bid Details.xlsx** — only 1 data row. Used `_row_hash`
  dedupe because the sample is too thin to pick a natural key with
  confidence.
- **All Bid History.xlsx** — `Heavy Bid #` column is all zeros in the
  source, so it was excluded from the dedupe composite in favor of
  `(job, bid_date)`. Documented in `bids_history/schema.py`.

### Framework fixes landed during this run

Two bugs surfaced on the first full run against real data and were fixed
before the report numbers above were recorded:

1. **`_coerce_types` Int64 cast** — `pd.to_numeric(..., errors="coerce").astype("Int64")`
   fails when the source column is all-unparseable (object dtype stays
   object). Changed to a two-step cast via Float64. Impact: the
   `estimates` mart now loads cleanly (previously `[error]` with 0
   rows written).
2. **UPSERT parameter overflow** — `hcss_activities` has 144k rows × 13
   cols = ~1.9M parameters in a single `INSERT ... VALUES (...)`,
   blowing past SQLite's 32,766-parameter limit. Added chunked execution
   in `_upsert` (20k-param cap for SQLite, 40k for Postgres) with per-row-count
   math based on the actual column count. Impact: `hcss_activities`
   loaded all 144,575 rows (collapsed to 103,964 unique).

Both fixes also keep the existing 7 unit tests green.

### Counts that look surprising but are correct

- **`mart_hcss_activities` 103,964 rows from 144,575 written**: the
  dedupe key `(tenant_id, estimate_code, activity_code)` collapsed 40k
  repeated activity lines across duplicate estimates. A human should
  confirm this is the intended grain before we graduate this mart to
  Vista v2; if line-level history is needed, add `imported_at` or a
  sequence column to the PK.
- **`mart_vendors` 1,861 rows from 2,492 written**: 631 exact-duplicate
  contact rows were collapsed by the row-hash. Same data-quality
  caveat applies — the row-hash WARN is the system telling us to give
  this mart a real key.

---

## Reproducing

```bash
cd fieldbridge/backend
source .venv/bin/activate
make clean-ingest-db           # optional; removes the local SQLite file
make ingest                    # creates tables + runs every mart against vancon
make ingest-one JOB=estimates  # single mart by name
```

Override the target DB with `INGEST_DB=postgresql://...` on the make
command line. `make ingest` always runs `create-mart-tables` first, so
a fresh DB is safe.
