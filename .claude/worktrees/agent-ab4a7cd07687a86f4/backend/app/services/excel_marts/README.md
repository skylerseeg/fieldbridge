# excel_marts
Excel-backed data marts for modules whose Vista equivalents aren't
wired yet. Each mart ingests one or more `.xlsx` files from
`data/vista_data/` into the tenant Postgres DB as `mart_*`
tables, then serves them through a FastAPI router.

When a module graduates to Vista, swap the `ingest.py` source from
Excel to `vista_sync` — `schema.py`, `service.py`, and the router
stay untouched.

## Conventions
- **Tenant-scoped**: every row carries `tenant_id` (FK → `tenants`).
  Preserves the multi-tenant isolation documented in `CLAUDE.md`.
- **Tables**: `mart_<module>_<entity>` (e.g. `mart_equipment_utilization`).
- **Alembic migrations** per mart — no raw DDL at runtime.
- **Read-only API**: ingest is a background / CLI job, never a request.

## Pattern per mart (one subdir per module)
```
excel_marts/<module>/
├── ingest.py    # Excel → mart_* tables (idempotent, UPSERT on natural key)
├── schema.py    # SQLAlchemy models + Pydantic DTOs (the Vista contract)
├── service.py   # Pure query/aggregation functions, tenant-scoped
└── __init__.py
```
Routers live at `backend/app/api/v1/<module>.py` and are registered in
`backend/app/api/v1/__init__.py` alongside existing routes.

## V1 scope
- **`equipment/`** — Equipment Utilization, Rentals, Fuel Totals, Employee Assets
  (feeds the Equipment Status Board, the current UI pilot)
- **`vendors/`** — Firm Contacts, Competitor Bids
  (feeds Supplier Enrichment)

Every other menu item (Bids, Jobs, Timecards, Fleet P&L, Cost Coding,
Proposals) gets a functional shell under the same pattern so the app
feels whole while we wait on Vista.

## Source files (see `docs/ARCHITECTURE.md` for full data→module map)
`data/vista_data/` — 28 `.xlsx` files (was 25 audited 2026-04-22; renamed and grew on 2026-04-28 with the Vendor_supplier addition + folder rename).
