# FieldBridge Data Mapping

This document maps source Excel files in `./vista_data/` to normalized
SQLite marts under `backend/app/services/excel_marts/<mart_name>/`.

## Principles

- One mart = one source shape. Joins happen in the service layer, not in ingest.
- Mart names are nouns, snake_case, no module prefix.
- Vista SQL graduation path documented per mart — when v2 lands, the ingest
  source swaps but the mart schema is stable.
- Menu modules consume one or more marts. A module is a UI concern; a mart is
  a data concern.

## Source → Mart → Module

| # | Source File | Mart (SQLite table) | Primary Menu Module | Secondary Consumers | Vista Tables (v2) | Priority |
|---|---|---|---|---|---|---|
| 1 | All Bid History.xlsx | `bids_history` | Bids | Executive Dashboard, Analytics | — | P2 |
| 2 | Bid History.xlsx | `bids_history_legacy` | Bids | — | — | P3 |
| 3 | Bid Outlook.xlsx | `bids_outlook` | Bids | Home, Executive Dashboard | — | P2 |
| 4 | Proposal Bids.xlsx | `proposals` | Proposals | Bids | — | P2 |
| 5 | Proposal Bid Details.xlsx | `proposal_line_items` | Proposals | Cost Coding | — | P2 |
| 6 | Competitor Bids.xlsx | `bids_competitors` | Bids | Recommendations | — | P2 |
| 7 | Estimates.xlsx | `estimates` | Cost Coding | Bids, Jobs | `jcjm` | P1 |
| 8 | Estimate Vs Actual.xlsx | `estimate_variance` | Executive Dashboard | Jobs | `jcjm` | P1 |
| 9 | HCSS Activities.xlsb | `hcss_activities` | Cost Coding | Estimates | — | P2 |
| 10 | Equipment Utilization.xlsx | `equipment_utilization` | Equipment | Fleet P&L, Predictive Maint. | `emem`, `emwo` | **P0** |
| 11 | Employee Assets.xlsx | `employee_assets` | Equipment | HR | `emem` | P1 |
| 12 | Rentals.xlsx | `equipment_rentals` | Equipment | Fleet P&L, Vendors/AP | `apvend` | P1 |
| 13 | Material analytics Fuel Totals.xlsx | `equipment_fuel` | Equipment | Fleet P&L | `emem` | P1 |
| 14 | Transfer Records.xlsx | `equipment_transfers` | Equipment | Activity Feed | `emwo` | P2 |
| 15 | Barcodes.xlsx | `asset_barcodes` | Equipment | Tool Room | `emem` | P3 |
| 16 | FabShopStockProducts.xlsx | `fabshop_inventory` | Equipment | Tool Room | — | P3 |
| 17 | Firm Contacts.xlsx | `vendors` | Vendors/AP | Bids, Recommendations | `apvend` | **P0** |
| 18 | Job Scheduling.xlsx | `job_schedule` | Jobs | Executive Dashboard | `jcjm` | P1 |
| 19 | WIP report - Job Scheduling.xlsx | `job_wip` | Jobs | Executive Dashboard, Fleet P&L | `jcjm` | P1 |
| 20 | Projected Hours.xlsx | `hours_projected` | Timecards | Jobs | `preh` | P2 |
| 21 | Job class FTE actual projections.xlsx | `fte_class_actual` | Timecards | Jobs | `preh` | P2 |
| 22 | Job class FTE Projections.xlsx | `fte_class_projected` | Timecards | Jobs | `preh` | P2 |
| 23 | Job type FTE actual.xlsx | `fte_type_actual` | Timecards | Jobs | `preh` | P2 |
| 24 | Overhead FTE Actuals.xlsx | `fte_overhead_actual` | Timecards | Executive Dashboard | `preh` | P2 |
| 25 | Overhead FTE Projections.xlsx | `fte_overhead_projected` | Timecards | Executive Dashboard | `preh` | P2 |

## Priority legend

- **P0** — v1 critical path. Must ingest before anything else ships.
- **P1** — Required for v1 UI to feel complete.
- **P2** — Ships with Phase 5 module UI.
- **P3** — Shell-only in v1; ingest can defer to v2.

## Module → Marts consumed

| Menu Module | Marts |
|---|---|
| Home | `equipment_utilization`, `job_wip`, `bids_outlook`, `estimate_variance` (summary reads only) |
| Executive Dashboard | `job_wip`, `estimate_variance`, `bids_outlook`, `fte_overhead_actual`, `fte_overhead_projected` |
| Activity Feed | `equipment_transfers`, `bids_history`, `proposals` (unioned event stream) |
| Equipment | `equipment_utilization`, `equipment_rentals`, `equipment_fuel`, `equipment_transfers`, `employee_assets`, `asset_barcodes`, `fabshop_inventory` |
| Work Orders | (derived — no direct Excel source; joins `equipment_utilization` + `equipment_transfers`) |
| Timecards | `fte_class_actual`, `fte_class_projected`, `fte_type_actual`, `fte_overhead_actual`, `fte_overhead_projected`, `hours_projected` |
| Jobs | `job_schedule`, `job_wip`, `estimate_variance` |
| Fleet P&L | `equipment_utilization`, `equipment_rentals`, `equipment_fuel` |
| Vendors / AP | `vendors`, `equipment_rentals` (vendor dim for rental spend) |
| Cost Coding | `estimates`, `hcss_activities`, `proposal_line_items` |
| Predictive Maint. | `equipment_utilization`, `equipment_fuel` (v3 shell only in v1) |
| Recommendations | all (LLM cross-mart synthesis) |
| Bids | `bids_history`, `bids_outlook`, `bids_competitors`, `proposals` |
| Proposals | `proposals`, `proposal_line_items` |
| Project Search | all (full-text index) |

## Dedupe key conventions

Ingest must pick a conservative dedupe key per mart. Prefer in this order:
1. Explicit ID column (job_id, vendor_id, asset_id, bid_id)
2. Composite natural key (e.g., asset_id + period_start for utilization)
3. Row hash of all non-null columns (fallback only — flag for review)

Any mart falling back to row-hash is logged as WARN in `ingest_log` so Skyler
can inspect and promote to a proper natural key.

## Mart → Vista graduation contract

Each mart's `schema.py` is the stable interface. When v2 swaps the ingest
source from Excel to Vista SQL, the Pydantic models and SQLite column names
stay identical. Only `ingest.py` changes. Test coverage on `service.py`
queries is the regression net.
