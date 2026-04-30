# Vista SQL — Strategic Read

**Source database**: VanCon Inc.'s Trimble Viewpoint Vista deployment.
**Connection**: `VCC-SVR01:1433/Viewpoint` as `Skyler` (privilege: `dbo`).
**Server**: Microsoft SQL Server 2016 (SP1-GDR), 13.0.4259.0 (X64).
**Captured**: 2026-04-30, full introspection via `backend/scripts/vista_introspect.py`.

---

## TL;DR

VanCon runs a complete, mature, multi-year Vista enterprise install. **2,277 tables, 104.9M rows.** Heavy data in Payroll, Imaging, Headquarters audit, Job Cost, GL, AP, Equipment. Light or empty in Service Management, Inventory, Project Management. **One unique custom dataset** — `budEMGPS` at 9.9M rows of equipment GPS coordinates, the moat asset that no other Vista contractor has by default.

---

## How Vista names its tables (read this first)

Vista's SQL Server schema uses two prefixes that confused the first introspection run:

| Prefix | Meaning | Examples |
|---|---|---|
| `b` | Base table — the canonical data | `bJCJM`, `bEMEM`, `bAPVM`, `bGLAC` |
| `v` | View-like table or generated view | `vSMAgreement`, `vDMAttachmentAuditLog`, `vPRTimecardSafetyNet` |
| `bud` / `vud` | User-Defined custom (Vista's extension mechanism) | `budEMGPS`, `budxa_NumbersTable_SQL` |

**The Vista module is the 2 letters AFTER the prefix.** So:

- `bJCJM` → `JC` (Job Cost) module, `JM` = Job Master
- `bEMEM` → `EM` (Equipment) module, `EM` = Equipment Master
- `vSMAgreement` → `SM` (Service Management) module
- `budEMGPS` → User-Defined, custom equipment GPS tracking

When `data/vista_schemas/*.md` and old code references things as `apvend`, `emem`, `emwo` — those are the **conceptual** names. The literal SQL names are `bAPVM`, `bEMEM`, `bEMWO`. They're the same entities, different namespaces.

---

## Scale snapshot

| Metric | Value | What it means |
|---|---|---|
| User tables | 2,277 | Full Vista enterprise install — every module provisioned |
| Total rows | 104,882,422 | Years of operational history |
| Foreign-key constraints | 2,347 | Heavy referential integrity — Vista enforces it |
| SQL Server version | 2016 SP1-GDR | Stable, supported tier |
| Connected user | `Skyler` (db_owner) | Full read/write privilege — discipline is on us, not Vista's RBAC |

---

## Module distribution

(Decoded from the b/v prefix; rolls up `bXX*` and `vXX*` into a single `XX` module.)

| Module | Total rows | Top tables | Read |
|---|---:|---|---|
| **IM** Imaging / Attachments | ~44.6M | `bIMWE_BAD_20130927` (44M, archive), `bIMWE` (580K, live) | The 44M-row archive is dead data — `_BAD_20130927` suffix indicates it was abandoned 2013-09-27. Live attachment data is 580K rows. |
| **HQ** Headquarters / Global | ~17.9M | `bHQMA` (15.8M), `bHQAI`, `bHQAT*` | Audit logs, master tables, attachments table. Cross-cutting infra. |
| **UD** User-Defined (custom) | ~12.5M | `budEMGPS` (9.9M), `budxa_NumbersTable_SQL` (1M) | **Moat data.** VanCon's custom Vista extensions. The GPS table is the standout. |
| **PR** Payroll | ~12.4M | `bPRTL` (3.8M), `bPRDT` (1.6M), `bPRJC` (1.2M), `bPRGL` (920K), `bPRRB` (884K), `bPRTH` (807K), `bPREA` (398K), `bPRER` (348K), plus `vPRTimecardSafetyNet` (729K), `vPR*` views (~1M) | **Heavy.** Multi-year timesheet, distribution, payroll-to-GL/JC crossover. Multiple supporting view tables. |
| **GL** General Ledger | ~4.3M | `bGLDT` (3.8M), `bGLAC` | Standard transaction detail + chart of accounts. |
| **AP** Accounts Payable | ~3.7M | `bAPTD` (1.35M), `bAPTL` (1.34M), `bAPVM` | Vendor transaction detail + line items + vendor master. |
| **JC** Job Cost | ~3.3M | `bJCCD` (2.6M), `bJCJM`, plus 90 supporting tables | **Core mart territory.** Cost detail = where every dollar lands. |
| **EM** Equipment | ~2.5M | `bEMRB` (1M, billing), `bEMRC`, `bEMRD` (437K), `bEMEM`, `bEMCO` | Equipment master, revenue billing, receipts, costs. |
| **DM** Document Management | ~2.0M | `vDMAttachmentAuditLog` (844K), 145 view tables | Document/attachment metadata. |
| **PM** Project Management | ~21K | `bPMPM` (master), `bPMFM`, 168 tables | **Light.** Many tables, very few rows — VanCon doesn't drive its work through PM module. |
| **SM** Service Management | ~2K | `vSMAgreement`, `vSMWorkOrderScope`, `vSMAgreementService` | **Empty.** Service Management isn't VanCon's business — they're heavy civil, not service contractors. |
| **BD** Bidding | 7.7K | 6 tables | Light internal Vista bidding. |
| **HR** Human Resources | 1.6K | 1 table | Minimal. |
| **IN** Inventory | 20 | 1 table | Effectively unused. |

**Practical takeaway:** the live data lives in **JC + EM + AP + GL + PR**. Custom value-add lives in **UD (budEMGPS)**. Skip SM, PM, BD, IN, HR for mart pipelines.

---

## The four canonical join targets

Foreign-key analysis surfaced the four most-referenced "entity" tables in Vista. **Every cross-module FieldBridge mart will eventually join on one of these:**

| Table | Inbound FKs | What it is |
|---|---:|---|
| `bGLAC` | 112 | GL Chart of Accounts — universal "what bucket / cost code" |
| `bPMPM` | 103 | Project Master — universal "what project" |
| `bJCJM` | 101 | Job Master — universal "what job" |
| `bEMEM` | 74 | Equipment Master — universal "what asset" |

If you're new to the Vista schema and want a starting point: read these four tables' columns first. Everything else hangs off them.

Secondary heavily-referenced targets:

| Table | Inbound FKs | Notes |
|---|---:|---|
| `bPMFM` | 55 | Project Management Form Master |
| `bEMCO` | 52 | Equipment Company |
| `vSMWorkOrderScope` | 42 | Service Management work order scope (mostly empty in VanCon) |
| `vSMAgreement` | 37 | Service Management agreement (mostly empty) |
| `bEMRC` | 36 | Equipment Receipts/Costs |
| `vSMAgreementService` | 36 | (mostly empty) |

---

## Custom data goldmine: `budEMGPS`

VanCon has a `bud*` extension — `budEMGPS` — with **9.9M rows of equipment GPS coordinates**. This isn't part of stock Vista. Someone (VanCon, a custom-mod vendor, an integration partner) built this `User-Defined` table years ago and has been logging GPS for the fleet on an ongoing basis.

**Strategic implications:**

- **No competitor contractor's Vista has this by default.** It's VanCon's data, full stop.
- 9.9M rows over multi-year window = the dataset is rich enough for trend analysis, geofencing, idle-time detection, asset-level utilization curves keyed on real movement (not just timesheet self-reporting).
- FieldBridge's Equipment module already has a Status Board mart pipeline. Layering `budEMGPS` joins onto `mart_equipment_utilization` lights up a real-time fleet-tracking surface that the existing UI can host without reshaping.
- This is a *unique* product surface — a marketing differentiator when FieldBridge sells to other Vista contractors who don't have the GPS extension.

**Next slice for this** (when prioritized): Phase 2 introspection script that drills into `budEMGPS` schema (column types, GPS coordinate format — lat/long pair vs WKT, sample rows, time-series structure) so the Equipment Worker can plan an `mart_equipment_gps` ingest.

---

## Imaging archive: ignore the 44M-row elephant

The largest table by row count is `bIMWE_BAD_20130927` (44M rows). The `_BAD_YYYYMMDD` naming convention is Vista's archive-rename pattern — when a table goes corrupt or gets superseded, Vista renames it with `_BAD_<date>` and starts fresh. This data is dead.

The live equivalent is `bIMWE` at 580K rows. **Use that for any imaging-attachment work; ignore the archive.**

If VanCon's DBA wants to free up disk, they can drop the archive. Out of scope for FieldBridge.

---

## What's NOT here

Vista modules with effectively zero data — don't build marts for these unless VanCon's business model shifts:

- **SM** Service Management (~2K rows): VanCon doesn't run service contracts.
- **IN** Inventory (20 rows): not a stock-managing operation.
- **BD** Bidding (7.7K rows): VanCon bids externally (NAPC, ITD, etc., per the Market Intel branch); internal Vista bidding module is barely touched.
- **HR** Human Resources (1.6K rows): payroll is heavy, but HR-module-specific tables aren't.
- **PM** Project Management (21K rows across 168 tables): big surface, light data — VanCon's project work flows through Job Cost, not PM.

---

## Refreshing this analysis

The strategic read above will drift as VanCon's Vista DB grows. To regenerate:

```bash
# From the WSL dev box (or the Render Shell once a network bridge to
# VCC-SVR01 is in place):
cd ~/fieldbridge/backend
.venv/bin/python3 scripts/vista_introspect.py

# Output:
#   - stdout summary (the table above)
#   - /tmp/vista_introspection_Viewpoint.json (full structured map)
```

For targeted drill into a specific table:

```bash
.venv/bin/python3 scripts/vista_introspect.py --extra-key-tables bIMWE,bAPVM
```

For the full JSON's column list of any key table:

```bash
jq '.key_table_columns.bJCCD.columns' /tmp/vista_introspection_Viewpoint.json
```

---

## Phase 2 candidates (drill scripts to write next)

Once we want to go deeper than module-level introspection, write per-table drill scripts in `backend/scripts/vista_*.py`:

| Script | Targets | Why |
|---|---|---|
| `vista_drill_jobcost.py` | `bJCJM`, `bJCCD`, `bJCCO`, plus FK joins | Job-cost data is the universal foundation; understanding the schema unlocks every operational mart |
| `vista_drill_equipment.py` | `bEMEM`, `bEMRB`, `bEMRC`, `bEMRD`, `bEMCO` | Equipment ownership cost + revenue billing — the basis for Fleet P&L mart |
| `vista_drill_payroll.py` | `bPRTH`, `bPRTL`, `bPRDT`, `bPRJC`, `bPRGL` | Heavy table count; need to understand timesheet → distribution → GL/JC posting chain |
| `vista_drill_ap.py` | `bAPVM`, `bAPTD`, `bAPTL`, `bAPCH`, `bAPLD` | Vendor master + transaction detail + line items + check headers |
| `vista_drill_gps.py` ⭐ | `budEMGPS` only | The moat. Sample rows, coordinate format, time-series shape, equipment-master join key |

Each drill script reuses `app.core.tenant.get_vista_connection_for_tenant`, runs SELECTs only, produces a per-table JSON + markdown summary. Same pattern as the broad-introspection script.

---

## Operating context

- **Read-only by hard rule.** Every script touching this DB is SELECT-only. CLAUDE.md: "Vista SQL is read-only. All writes go through the Vista REST API or CSV import."
- **No mart writes against Vista directly.** Marts live in FieldBridge's own Postgres (`fieldbridge-db` on Render), populated by ingest jobs that READ Vista and WRITE to `mart_*` tables.
- **Privilege level for exploration is `dbo`** — Skyler's login is the database owner. Discipline matters; a fat-fingered UPDATE or DROP would land. Run scripts, not ad-hoc queries in SSMS, when in doubt.
- **Connection topology**: today, exploration runs from the WSL dev box on the VanCon network. Render Cron Jobs cannot reach `VCC-SVR01` (it's a local hostname, no public route from Render's Oregon datacenter). Production cron access requires a network bridge (Cloudflare Tunnel, Tailscale, or VPN) — out of scope for v1.5.

---

## Document maintenance

This is a living strategic-read snapshot. Update when:

- Re-running `vista_introspect.py` shows materially different module totals (e.g. budEMGPS doubles in size, or a new `_BAD_*` archive appears)
- VanCon adopts a new Vista module (SM going live, IN starting to track inventory, etc.)
- A new `bud*` custom table surfaces — those are operationally interesting because they're VanCon-specific
- Phase 2 drill scripts produce schema-level findings worth quoting at the strategic layer

Last updated: 2026-04-30 by Lead Agent. Next planned refresh: after Phase 2 drill scripts (per priority).
