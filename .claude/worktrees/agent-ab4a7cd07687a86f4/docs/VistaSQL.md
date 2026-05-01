# Vista SQL — Strategic Read

> 🚨 **2026-05-01 — IMPORTANT STATUS UPDATE**
>
> The content below was captured against **`VCC-SVR01.Viewpoint`** (SQL Server 2016 SP1-GDR, build 13.0.4259.0). Trimble support confirmed via email that this server is NOT the live production Vista — VanCon's actual production Vista lives on **`KWMFD1`** (SQL Server 2019, build 15.0.4465.1), which we have not yet introspected.
>
> **What this means for the strategic read below:**
> - The 2,277 tables / 104.9M rows / module breakdown all describe a **secondary or archive server**, likely retired around April 2024 when VanCon migrated production Vista to KWMFD1. (That migration date matches the freshness ceiling on every operational table.)
> - The module-distribution patterns are still useful as a *Vista shape primer* — the b/v/bud naming convention, the canonical join targets (bGLAC, bPMPM, bJCJM, bEMEM), the moat-data pattern (budEMGPS, etc.) all carry over to KWMFD1 since it's the same Vista application.
> - But specific row counts, freshness ranges, and "what's empty" judgments are **not authoritative** — they reflect the secondary server, not live operations.
>
> **What's pending:** SQL Auth credentials for KWMFD1 (Trimble or VanCon's DBA), reconfigure `.env`, re-run `vista_introspect.py`, refresh this doc with the live KWMFD1 numbers. Until then, treat the data below as an artifact of the secondary server.
>
> ---

**Source database (this snapshot)**: VanCon Inc.'s legacy Vista server, retained after migration to KWMFD1.
**Connection**: `VCC-SVR01:1433/Viewpoint` as `Skyler` (privilege: `dbo`).
**Server**: Microsoft SQL Server 2016 (SP1-GDR), 13.0.4259.0 (X64).
**Captured**: 2026-04-30, full introspection via `backend/scripts/vista_introspect.py`.

**Live production target (pending introspection)**: `KWMFD1.Viewpoint` (SQL Server 2019, build 15.0.4465.1).

---

## TL;DR — secondary-server snapshot (NOT live ops)

VCC-SVR01 hosts a complete Vista enterprise install with multi-year history. **2,277 tables, 104.9M rows.** Heavy data in Payroll, Imaging, Headquarters audit, Job Cost, GL, AP, Equipment. Light or empty in Service Management, Inventory, Project Management. **One unique custom dataset** — `budEMGPS` at 9.9M rows of equipment GPS coordinates, the moat asset that no other Vista contractor has by default. **All numbers below describe state as of ~April 2024**; live operations have continued on KWMFD1 since.

> ⚠️ **Data-freshness flag (resolved)**: the April-2024 ceiling on every operational table was the smoking gun for the secondary-server theory. Confirmed 2026-05-01 via Trimble support: VCC-SVR01 is not the live production Vista. KWMFD1 is. Old freshness section retained below for reference.

> ⚠️ **`bEMWO` (Equipment Work Orders) does not exist in this database.** VanCon either doesn't use Vista's EM Work Orders module or tracks work orders in a custom table not yet identified. Phase 2 drill should locate the actual work-order surface (likely a `bud*` extension or HCSS-side data).

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

| Module | Tables | Total rows | Top tables | Read |
|---|---:|---:|---|---|
| **IM** Imaging / Attachments | 20 | 44,642,081 | `bIMWE_BAD_20130927` (44M, archive), `bIMWE` (580K, live) | The 44M-row archive is dead data — `_BAD_20130927` suffix indicates it was abandoned 2013-09-27. Live attachment data is 580K rows. |
| **HQ** Headquarters / Global | 78 | 17,918,563 | `bHQMA` (15.8M), `bHQAI` (891K), `bHQAT*` (586K + 393K) | Audit logs, master tables, attachments table. Cross-cutting infra. |
| **PR** Payroll | 226 | 11,863,088 | `bPRTL` (3.8M), `bPRDT` (1.6M), `bPRJC` (1.2M), `bPRGL` (920K), `bPRRB` (884K), `bPRTH` (807K), `bPREA` (398K), `bPRER` (348K), plus `vPRTimecardSafetyNet` (729K) | **Heavy.** Multi-year timesheet, distribution, payroll-to-GL/JC crossover. |
| **UD** User-Defined (custom) | 93 | 11,527,068 | `budEMGPS` (9.9M), `budxa_NumbersTable_SQL` (1M) | **Moat data.** VanCon's custom Vista extensions. The GPS table is the standout. |
| **GL** General Ledger | 37 | 4,312,564 | `bGLDT` (3.8M), `bGLAC` (chart of accounts) | Transaction detail + chart of accounts. |
| **AP** Accounts Payable | 65 | 3,528,255 | `bAPTD` (1.35M), `bAPTL` (1.34M), `bAPVM` (3,300 vendors) | Vendor transaction detail + line items + vendor master. |
| **JC** Job Cost | 86 | 3,220,059 | `bJCCD` (2.6M), `bJCJM` (1,123 jobs) | **Core mart territory.** Cost detail = where every dollar lands. Note: `bJCJM` only counts certified-with-CertDate jobs; current open jobs likely live elsewhere or have null CertDate. |
| **EM** Equipment | 83 | 2,449,869 | `bEMRB` (1M billing), `bEMRD` (437K), `bEMEM` (1,746 assets), `bEMRC`, `bEMCO` | Equipment master, revenue billing, receipts/costs. |
| **DM** Document Management | 11 | 844,317 | `vDMAttachmentAuditLog` (844K) | Document/attachment metadata. |
| **PM** Project Management | 281 | 506,306 | `bPMPM` (master, 103 inbound FKs!), `bPMFM` (55 inbound FKs) | **Heavy FK target, lighter actual data.** PM master is the second most-referenced entity in the FK map but the operational rows are modest. Worth understanding the join pattern even if mart pipelines don't read PM heavily. |
| **DB** Database / Sysadmin | 9 | 405,803 | Vista internal | Skip. |
| **RP** Reporting | 41 | 271,583 | Various | Vista's own reporting metadata; FieldBridge replaces this surface. |
| **AR** Accounts Receivable | 24 | 250,586 | Various | AR data exists but VanCon's billing model is heavy on equipment-revenue-billing (`bEMRB`) rather than traditional AR aging. |
| **HR** Human Resources | 65 | 126,045 | Various | Light. |
| **PO** Purchase Order | 39 | 110,114 | Various | Light. PO module is provisioned but lightly used — likely VanCon does most procurement through AP direct rather than PO-first workflow. |
| **CM** Cash Management | 10 | 83,574 | Various | Bank reconciliation surface. |
| **SL** Subcontract | 24 | 21,639 | Various | Light. |
| **VA** VendorPay / ACH | 23 | 1,153 | Various | Light — VanCon may not use Vista's ACH module. |
| **SM** Service Management | 157 | 408 | `vSMAgreement`, `vSMWorkOrderScope`, `vSMAgreementService` (each 36-42 inbound FKs but ~empty data) | **Empty data, heavy FK references.** The schema is wired up but no service operations. VanCon is heavy civil, not service contractors. |
| **MS** Material Sales | 63 | 1 | — | Effectively unused. |
| **IN** Inventory | 40 | 57 | — | Effectively unused. |
| **BD** Bidding | 0 found | — | — | (Note: my earlier "BD = 7.7K" reading was incorrect — was bucketing `b*` non-Vista tables. The actual `bBD*` module isn't materially populated here.) |

Plus dozens of smaller "Unknown" prefix buckets — `UX`, `DD`, `OL`, `JB`, `VP`, etc. — that are likely Vista internal categories or VanCon-specific patterns. Lower priority for FieldBridge mart pipelines.

**Practical takeaway:** the operational data lives in **JC + EM + AP + GL + PR**. Custom value-add lives in **UD (budEMGPS)**. PM is a referential anchor (heavy FK target) but lighter on operational data. Skip SM, IN, MS, BD for mart pipelines — VanCon doesn't operate through those modules.

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

## Key tables — column shape + freshness

Captured 2026-04-30 by `vista_introspect.py --mode full`:

| Table | Cols | Rows | Date column | First record | Last record | Notes |
|---|---:|---:|---|---|---|---|
| `bAPTD` | 33 | 1,350,631 | `Mth` | 2012-12 | 2024-04 | AP transaction detail |
| `bAPTL` | 77 | 1,344,848 | `Mth` | 2012-12 | 2024-04 | AP transaction lines (wide table) |
| `bAPVM` | 113 | 3,300 | `LastInvDate` | 2000-10-07 | **2043-03-24** ⚠ | Vendor master. The 2043 date is suspicious — probably a typo or placeholder; most contractor vendor masters carry a few of these. Worth a one-off SELECT to identify the bad row(s). |
| `bEMCO` | 81 | 5 | `DeprLstMnthCalc` | 2015-06 | 2024-02 | Equipment company config — only 5 rows = 5 companies tracked. |
| `bEMEM` | 133 | 1,746 | `OdoDate` | 2013-02-19 | 2024-04-03 | Equipment master. **1,746 assets** = VanCon's full fleet count. 133 columns = wide master with depreciation, GPS device IDs, etc. |
| `bEMRB` | 11 | 1,077,943 | `Mth` | 2013-01 | 2024-04 | Equipment revenue billing — basis for Fleet P&L. |
| `bEMRC` | 13 | — | — | — | — | Equipment receipts/costs (no date column) |
| `bGLAC` | 24 | — | — | — | — | Chart of accounts (no date column — it's a master). 112 inbound FKs — universal join target. |
| `bGLDT` | 21 | 3,839,200 | `Mth` | 2012-12 | **2024-12** | GL detail. Last data Dec 2024. |
| `bHQCO` | 38 | — | — | — | — | Company master (no date column) |
| `bHQMA` | 11 | 15,837,887 | `DateTime` | 2012-08-22 | **2025-06-16** | Master audit log — most recent-touching table in the DB. |
| `bJCCD` | 107 | 2,602,894 | `Mth` | 2012-11 | **2024-12** | Job cost detail — 12 years of cost-by-cost-code. **The operational heart.** |
| `bJCCO` | 70 | — | — | — | — | Job cost company config |
| `bJCJM` | 106 | 1,123 | `CertDate` | 2015-11-13 | 2023-09-01 | Job master, **only certified jobs**. CertDate-based filter — current open jobs likely have null CertDate and are excluded from this count. |
| `bPMPM` | 34 | — | — | — | — | Project master — 103 inbound FKs (second most-referenced entity) |
| `bPRDT` | 30 | 1,593,780 | `PREndDate` | 2015-06-18 | 2024-04-06 | Payroll distribution detail |
| `bPRJC` | 42 | 1,207,379 | `PREndDate` | 2015-06-18 | 2024-04-06 | Payroll-to-Job-Cost crossover |
| `bPRTH` | 63 | 806,765 | `PREndDate` | 2015-06-18 | 2024-04-06 | Timesheet header |
| `bPRTL` | 9 | 3,853,589 | `PREndDate` | 2015-06-18 | 2024-04-06 | Timesheet line — narrow, deep |
| `budEMGPS` ⭐ | 25 | 9,931,359 | `ReadingDate` | 2021-11-12 | 2024-04-15 | **Custom GPS extension.** 25 columns of structure to investigate in Phase 2. ~2.5 years of fleet movement (Nov 2021 → Apr 2024). |

**`bEMWO` not found** — see "Missing tables" below.

---

## Data freshness

The `Last record` column above tells a story: **most operational data ends around April 2024**, with `bGLDT` and `bJCCD` reaching December 2024 and `bHQMA` (audit log) reaching June 2025.

Today is 2026-04-30. **The data is 12-24 months stale relative to today.**

| Table | Most recent | Approx age vs. 2026-04-30 |
|---|---|---|
| `bAPTD`, `bAPTL`, `bEMRB`, `bEMCO`, `bEMEM`, `budEMGPS`, `bPRDT`, `bPRJC`, `bPRTH`, `bPRTL` | April 2024 | ~24 months |
| `bGLDT`, `bJCCD` | December 2024 | ~16 months |
| `bJCJM` (CertDate) | September 2023 | ~31 months (likely just open-job exclusion, not a freshness issue) |
| `bHQMA` (audit log) | June 2025 | ~10 months |

**Most likely interpretation:** `VCC-SVR01.Viewpoint` is a **staging/reporting snapshot**, refreshed monthly or quarterly, not the live production Vista. Many contractors run a separate read-only SQL instance for ETL, reporting, and BI tools to keep that workload off the production server. The audit log being more recent than the operational tables is consistent with this — audit might be replicating on a different schedule than the data tables.

**What to do about it:**

1. **Confirm with VanCon's DBA.** Ask: "Is `VCC-SVR01.Viewpoint` the live production Vista or a staging/reporting snapshot? When was it last refreshed? Is there a different SQL instance for live operational data?"
2. **If staging:** decide whether FieldBridge marts should use this read-replica (lower load on prod, but stale) or whether we need access to the live instance (current data, more sensitive).
3. **If live but somehow stale:** investigate why no operational rows since April 2024. Possible causes: a Vista module being decommissioned, a parallel system taking over, or a backup-and-restore that didn't capture recent transactions.

This is a **strategic input** for the FieldBridge Vista integration story. Don't build mart pipelines against this connection until the freshness question is answered.

---

## Missing tables

`bEMWO` (Equipment Work Orders) — referenced in `data/vista_schemas/emwo.md` and the v1 backend's onboarding test (`test_vista_connection` queries `emem` for active equipment), but **does not exist** in this database.

Possibilities:

1. VanCon doesn't use Vista's Equipment Work Orders module. Work orders may live in HCSS, a custom `bud*` table, or paper.
2. Naming variation — VanCon may use a custom-renamed equivalent.
3. The module was never provisioned at install.

**Phase 2 investigation:** search for tables matching `*WorkOrder*`, `*WO*`, `bud*EM*` patterns to locate the actual work-order surface, then update `data/vista_schemas/emwo.md` with the real table name.

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
