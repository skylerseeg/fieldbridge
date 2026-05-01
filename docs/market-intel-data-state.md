# Market Intel — Data State (Phase 0)

> **Purpose.** A single point-in-time inventory of what data exists, where it lives, what's populated vs. mocked vs. planned, and which surfaces are gated on external blockers. This is the prerequisite to any further Market Intel feature code — every Phase 1+ decision should cite this doc as the as-built reference.
>
> **Companion doc:** `docs/market-intel.md` describes the **intended design** of v1.5 (the "why"). This doc describes the **current state** (the "what"). They are deliberately separate.
>
> **Captured:** 2026-05-01. Refresh whenever a major data surface lands (new mart, scraper, KWMF-sql access, etc.).

---

## TL;DR

- Two parallel data sources for bid intelligence today: **Excel marts** (live on `main`) and **scraped public bids** (live on `feature/market-intel-v15`, NOT YET MERGED to main).
- Excel marts are the historical-VanCon-data side: bid history, proposal line items, vendor master. Populated, query-ready.
- Scraped bids are the public-competitor-data side: ITD (Idaho) only is functional; NAPC paused at robots.txt; other state DOTs are stubs.
- **Daily refresh exists for the scraper side** (Render Cron Job, `0 9 * * *` UTC) — but only on the feature branch. Main has no scheduled jobs yet.
- **Vista live data is gated** on KWMF-sql.viewpointdata.cloud SQL Auth credentials from Trimble (network path verified, login provisioning pending).
- **Schema is "almost ready" for Layer A/B forward-compat,** but missing 6 columns on `bid_events`, 5 on `bid_results`, 1 entire table (`vancon_bid_breakdowns`). Phase 1 adds these without disturbing existing code.

---

## 1. Current data inventory

### 1a. On `main` — Excel marts (live, populated)

These ship today and are loaded via `python scripts/run_ingest.py --tenant vancon --job <name>`. Source files live in `data/vista_data/*.xlsx` (or `.xlsb` for HCSS). Every table is tenant-scoped.

| Table | Source file | Rows (recent run) | Status | Notes |
|---|---|---:|---|---|
| `mart_bids_history` | All Bid History.xlsx | populated | ✅ live | The wide table — has `bid_1..17_comp`, `bid_1..17_amt`, `bid_1..17_won` for up to 17 competitors per row. Rich. |
| `mart_bids_history_legacy` | Bid History.xlsx | populated | ✅ live | Subset of the above, deduped identically. Drops the wide competitor columns. |
| `mart_bids_competitors` | Competitor Bids.xlsx | **0 rows** | ⚠ empty | Schema exists, source Excel never populated. |
| `mart_bids_outlook` | Bid Outlook.xlsx | populated | ✅ live | 33% of rows have null `bid_date`. Pre-bid pipeline data. |
| `mart_proposals` | Proposal Bids.xlsx | **2 rows** | ⚠ thin | Sample only — not the real proposal feed. |
| `mart_proposal_line_items` | Proposal Bid Details.xlsx | populated | ⚠ orphaned | Row-hash dedupe key. **No FK back to `mart_proposals.job/owner/bid_type`** — can't join detail to summary today. |
| `mart_vendors` | Firm Contacts.xlsx + Vista `apvend` | ~46K | ✅ live | 46% null name, 82% null email. Free-form `code_1..5` (40 chars) — no enforced taxonomy. |
| `mart_vendor_enrichments` | (overlay, written via API) | per-tenant | ✅ live | Per-tenant + per-vendor overlay table. Read pattern is LEFT JOIN with coalesce. |

**Equipment marts** (`mart_equipment_utilization`, `mart_equipment_fuel`, `mart_equipment_rentals`, `mart_equipment_transfers`) — fully populated, verified on Render 2026-05-01. Not directly Bid Intelligence but listed for completeness; will be relevant for Layer A's equipment-cost-bucket reconstruction.

### 1b. On `feature/market-intel-v15` — Scraped public bid data (NOT YET ON MAIN)

Schema exists, scraper exists, cron exists. **Branch has not been merged to main yet** — the only reason this section is documented before merge is that the merge is the immediate gating decision for any further work.

| Table | Source | Rows | Status | Notes |
|---|---|---:|---|---|
| `bid_events` | ITD bid abstract PDFs (Idaho only) | depends on cron runs since deploy | 🟡 functional, 1 state | Tenant-scoped to `SHARED_NETWORK_TENANT_ID`. JSON `csi_codes` column. |
| `bid_results` | One row per bidder per `bid_events` row | proportional to bid_events × ~3-8 bidders avg | 🟡 functional, 1 state | `is_low_bidder` denormalized for fast indexed reads. |
| `contractors` | Resolved from `bid_results.contractor_name` via fuzzy match | proportional to unique vendors observed | 🟡 functional | RapidFuzz `token_set_ratio` ≥ 92. Best-effort `apvend_match_id` for Vista vendor crossover. |

### 1c. Pending / blocked

| Surface | What's missing | Blocker |
|---|---|---|
| Vista live job cost (bJCCD) | Live data per bid event for joining to scraped bids | KWMF-sql.viewpointdata.cloud SQL Auth credentials |
| Vista vendor master (bAPVM live) | Up-to-date vendor records for `contractors.apvend_match_id` resolution | Same |
| `vancon_bid_breakdowns` table | The Layer A foundation — VanCon's internal cost-bucket per bid | Phase 1 schema PR + post-Vista data |
| Other state DOT scrapers | UT, WA, OR, CA, MT, WY, NM, AZ | Engineering — none built; only ITD ships |
| NAPC scraping | Public bid solicitations across all 50 states | Paused permanently per their robots.txt; pivoted to State DOT model |

---

## 2. Pipeline cadence

### 2a. Excel mart ingest (manual today, daily later)

- **Trigger:** `python scripts/run_ingest.py --tenant vancon --job <name>` — manual, on-demand.
- **Schedule:** None. There is no cron job for Excel ingest.
- **Why manual:** The source Excels live in the repo (`data/vista_data/`) and update only when an operator commits a refresh. No upstream feed pushing them.
- **Gap:** Once VanCon's existing webapps publish their Excel exports somewhere fetchable (S3, SharePoint, Drive), a daily ingest is straightforward — same `run_ingest.py` invocation in a Render Cron service.

### 2b. ITD scraper (daily on feature branch)

- **Trigger:** Render Cron Job `fieldbridge-itd-pipeline`, scheduled `0 9 * * *` UTC (≈ 03:00 MDT / 02:00 MST). Runs nightly.
- **Code:** `python scripts/run_itd_pipeline.py --state ID` — one-shot, exits 0 on clean run.
- **What it does:**
  1. Discover ITD bid abstract URLs from `https://itd.idaho.gov/contractor-bidding/`.
  2. Fetch each via `HttpFetcher` (robots-aware, rate-limited).
  3. Parse with `pdfplumber` → `ParsedBidPost` (page 1 only — AASHTOWare Vendor Ranking summary).
  4. Idempotency-check via `(source_url, raw_html_hash)` unique constraint.
  5. Write `BidEvent` + `BidResult` rows under `SHARED_NETWORK_TENANT_ID`.
- **Operational signal today:** Exit code only. Render's dashboard shows ✅ / ❌ per run. **There is no `pipeline_runs` table** (proposed in Phase 2) — to debug a missed/anomalous run today, read the cron service's Render logs.
- **n8n flow** committed at `workers/n8n_flows/market_intel_daily.json` as documentation; not active. The Render Cron path is canonical.

### 2c. What "daily" doesn't yet mean

- No materialized views are refreshed on a schedule. The analytics SQL files (`backend/app/services/market_intel/analytics/{bid_calibration,competitor_curves,opportunity_gaps}.sql`) are queries the API runs on demand, not maintained MVs. Performance is fine at current row counts (single-state, weeks of data); will need MVs at multi-state scale.
- No data-freshness banner in the UI. If the cron silently fails for 3 days, the operator finds out by checking Render Events. Phase 2 of the operator's plan calls for a banner driven by `pipeline_runs.last_success_at`.

---

## 3. Vista access blockers

The full diagnostic chain ran today (2026-05-01) is in `docs/VistaSQL.md` (now updated with the patched-introspection numbers). Summary as it pertains to Bid Intelligence:

- **VCC-SVR01.VCC.local** (secondary/archive Vista): 100% accessible. Read-only via `Skyler` login. Useful for historical exploration but **not for live data** — operational tables (bAPTD, bJCCD, bEMRB, bPRTL, etc.) all stop **April 2024**.
- **KWMF-sql.viewpointdata.cloud:4986** (Trimble-hosted live Vista): network path verified end-to-end (DNS + TCP + TLS + SQL TDS handshake). **Login `Skyler` not yet provisioned** on the new instance — clean SQL Server `error 18456 / SQLState 28000`. Awaiting Trimble (Case #32788945, Rick Vander Ley) to provision read-only SQL Auth.
- **Effect on Bid Intelligence specifically:**
  - Layer A's `vancon_bid_breakdowns` table can be created today (Phase 1) but cannot be **populated** with live VanCon bid breakdowns until KWMF-sql is up. The Excel mart `mart_bids_history` and `mart_proposal_line_items` are the interim populator.
  - Contractor → vendor crossover (`contractors.apvend_match_id`) currently resolves against **secondary** apvend (3,300 vendors as of April 2024). Once live KWMF-sql is up, this resolver should re-run against the live apvend.
- **What's NOT blocked:**
  - Phase 1 schema additions — pure DDL, no Vista dependency.
  - Phase 2 daily cron + ops banner — uses the bid_events/bid_results data already accumulating from ITD.
  - Phase 3 job-type taxonomy — operates on `bid_events.work_scope` text, no Vista needed.

---

## 4. Coverage gaps

### 4a. State DOT scraper coverage

| State | Status | Source pattern | Notes |
|---|---|---|---|
| **ID** | ✅ functional | AASHTOWare PDF abstracts at `apps.itd.idaho.gov` | Page-1 parser. 30 fixtures captured. Two template variants (`aashtoware_v1`, `itd_legacy`) — only v1 parses; legacy logged + skipped. |
| UT | ⏳ stub | TBD | Operator's home state. Highest priority next. UDOT publishes bid tabs — format unknown. |
| OR | ⏳ stub | TBD | ODOT. AASHTOWare-using state, may share template with ID. |
| WA | ⏳ stub | TBD | WSDOT. AASHTOWare-using state. |
| MT, WY, NM, AZ, CA | ⏳ stub | TBD | Lower priority, but the regional supplier-network analysis (Layer B) wants ≥4 states for meaningful geographic coverage. |
| Other 40 | ❌ no plan | — | Out of scope for v1.5. v3 conversation. |

### 4b. NAPC network — paused

Captured in `backend/app/services/market_intel/scrapers/napc_network/_napc_paused.md` and `state_portal_registry.json` (2026-04-29 probe results). The registry has all 50 states' `*bids.com` / `*bids.net` URLs probed, but no scraper runs them — robots.txt deny prevented engineering, operator authorized pivot to State DOT model.

The registry is **not deleted** — it remains as a starting point if NAPC outreach succeeds and licensed access opens that path.

### 4c. Geographic gap for Layer B

Layer B (supplier/sub intelligence) wants per-county coverage of winning bidders. Today the data covers Idaho counties only. Until at least UT + 1 neighboring state ship, "regional supplier network" is a single-state observation, not a regional one. **Don't market Layer B on existing data; build UT scraper first.**

---

## 5. Schema as-built

### 5a. `bid_events` (on `feature/market-intel-v15`)

Columns currently defined:

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | String(36) PK | no | UUID4. |
| `tenant_id` | String(36) FK → tenants.id | no | Index. ON DELETE CASCADE. |
| `source_url` | Text | no | Part of unique constraint with `tenant_id`, `raw_html_hash`. |
| `source_state` | CHAR(2) | no | Origin state of the scraper (vs. `location_state` which is project location). |
| `source_network` | String(40) | no | `'napc' \| 'bidnet' \| 'state_dot_ut' \| 'state_dot_id' \| ...` |
| `solicitation_id` | String(120) | yes | Vendor-published bid number when available. |
| `raw_html_hash` | CHAR(64) | no | SHA-256 of raw scraped doc. Idempotency. |
| `project_title` | Text | no | |
| `project_owner` | Text | yes | "City of Boise", "ITD", etc. |
| `work_scope` | Text | yes | The free-form scope text — Phase 3 taxonomy will derive `job_type` from this. |
| `csi_codes` | JSON (list[str]) | yes | 4-digit Vista CSI format. **JSON not ARRAY** for SQLite test compat. |
| `bid_open_date` | Date | yes | Index. |
| `bid_status` | String(20) | yes | `'open' \| 'closed' \| 'awarded' \| 'cancelled'` |
| `location_city` | String(120) | yes | |
| `location_county` | String(120) | yes | |
| `location_state` | CHAR(2) | yes | Index. Composite index with tenant_id + bid_open_date. |
| `scraped_at` | DateTime(tz) | no | Default `now(utc)`. |

Constraints:
- `uq_bid_events_source` on `(tenant_id, source_url, raw_html_hash)`.
- `ix_bid_events_tenant_state_date` on `(tenant_id, location_state, bid_open_date)`.

Relationships:
- `results: list[BidResult]` (cascade delete-orphan, lazy="selectin").

### 5b. `bid_results` (on `feature/market-intel-v15`)

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | String(36) PK | no | UUID4. |
| `tenant_id` | String(36) FK → tenants.id | no | Index. |
| `bid_event_id` | String(36) FK → bid_events.id | no | Index. ON DELETE CASCADE. |
| `contractor_name` | Text | no | Raw observed string (variant). |
| `contractor_url` | Text | yes | Bidder website if scraped. |
| `bid_amount` | Numeric(14,2) | yes | NULL when only the low is published. |
| `is_low_bidder` | Boolean | no | Default false. Denormalized for indexed reads. |
| `is_awarded` | Boolean | no | Default false. |
| `rank` | Integer | yes | 1 = low. NULL when not all bids ranked. |

Constraints:
- `uq_bid_results_event_contractor` on `(bid_event_id, contractor_name)`.
- `ix_bid_results_tenant_contractor` on `(tenant_id, contractor_name)`.

Relationships:
- `event: BidEvent` (back_populates="results", lazy="joined").

### 5c. `contractors` (on `feature/market-intel-v15`)

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | String(36) PK | no | UUID4. |
| `tenant_id` | String(36) FK → tenants.id | no | Default = `SHARED_NETWORK_TENANT_ID`. |
| `canonical_name` | Text | no | The de-suffixed, case-collapsed canonical form. |
| `name_variants` | JSON (list[str]) | yes | All raw bidder strings observed. **JSON not ARRAY** for SQLite test compat. |
| `headquarters_state` | CHAR(2) | yes | Inferred or explicitly captured. |
| `apvend_match_id` | String(40) | yes | Vista `apvend.Vendor` match. Best-effort, can be NULL. |
| `win_count` | Integer | no | Default 0. Maintained by analytics layer. |
| `bid_count` | Integer | no | Default 0. |
| `median_bid` | Numeric(14,2) | yes | Maintained by analytics layer. |

Constraints:
- `uq_contractors_tenant_name` on `(tenant_id, canonical_name)`.

---

## 6. Forward-compat assessment for Phase 1

The operator's Phase 1 schema additions plan was reviewed against the as-built schema. Findings, column-by-column:

### 6a. `bid_events` proposed additions

| Proposed column | Collision check | Recommendation |
|---|---|---|
| `job_type` (Text) | None — no existing column. | ✅ Add. |
| `job_subtype` (Text) | None. | ✅ Add. |
| `csi_codes` (Text[]) | **Already exists as JSON.** Plan listed as "additions" but it's there. | 🟡 Plan should drop this row from Phase 1 PR — already shipped on the feature branch. |
| `scope_keywords` (Text[]) | None. | ✅ Add as JSON for SQLite parity (same rationale as `csi_codes`). |
| `agency_type` (Text) | None. | ✅ Add. |
| `funding_source` (Text) | None. | ✅ Add. |
| `project_size_band` (Text) | None. | ✅ Add. Consider if this should be a generated column from `engineer_estimate` — cheaper to compute once, queryable for life. |
| `prevailing_wage` (Boolean) | None. | ✅ Add. |
| `bid_open_date` (Date) | **Already exists**, indexed. | 🟡 Drop from PR — shipped. |
| `award_date` (Date) | None. | ✅ Add. |
| `engineer_estimate` (Numeric) | None. | ✅ Add. Numeric(14,2). |

### 6b. `bid_results` proposed additions

| Proposed column | Collision check | Recommendation |
|---|---|---|
| `bid_amount` (Numeric) | **Already exists.** | 🟡 Drop from PR — shipped. |
| `pct_above_low` (generated col) | None. | ✅ Add as Postgres generated column **and** SQLite-equivalent (computed in Python on insert, with a CHECK constraint clarifying the formula). Postgres generated columns aren't supported in SQLite, so we either use a trigger or compute on write — recommend compute on write to keep CI tests passing. |
| `is_disqualified` (Boolean) | None. | ✅ Add, default false. |
| `bond_amount` (Numeric) | None. | ✅ Add. Numeric(14,2). |
| `listed_subs` (JSONB) | None. | ✅ Add as JSON (cross-dialect). Schema TBD — propose `[{name, scope, amount, csi_code}]`. |
| `listed_suppliers` (JSONB) | None. | ✅ Add as JSON. Same shape concept as `listed_subs`. |

### 6c. `vancon_bid_breakdowns` (new table)

| Concern | Assessment |
|---|---|
| Naming | Aligned with mart_* convention. Consider `mart_vancon_bid_breakdowns` to match the Excel mart family — or keep without prefix to signal it's NOT an Excel mart, it's a Vista/derived table. **Recommend:** drop `mart_` prefix; this is a Vista/derived surface, not an Excel-driven one. |
| `bid_event_id` FK | ✅ Required. Phase 1 PR ships this. |
| `cost_buckets` JSONB shape | Define enum: `{labor, materials, equipment, subs, overhead}` — keep small to start, expand under additive migrations. |
| `crew_composition`, `equipment_mix` JSONB | ✅ Add. Shape free-form for v1, enforce in v2 if patterns stabilize. |
| `sub_quotes`, `supplier_quotes` JSONB | ✅ Add. The `used: bool` field is the key — distinguishes "sub we got a quote from" vs. "sub we actually used in our submitted bid". |
| `vista_estimate_id` | ✅ Add. Will be NULL until KWMF-sql access. UNIQUE constraint per the plan. |
| Tenant scope | **Per-customer-tenant, NOT shared-network.** This is VanCon's internal data; never share with other tenants. |

### 6d. Operational columns the plan didn't propose but should

| Column | Where | Why |
|---|---|---|
| `pipeline_run_id` (FK → pipeline_runs.id) | `bid_events`, `bid_results` | Phase 2 wants run-level traceability. Cheap to add now under additive migration. |
| `created_at`, `updated_at` (DateTime, default now) | All three Market Intel tables | Currently only `scraped_at` exists on `bid_events`. Add for forward-compat with audit and "fresh since" queries. |
| `tenant_id` on `vancon_bid_breakdowns` | (table) | Required by tenant-scoping convention. Plan implies but doesn't list. |

### 6e. Migration ordering

If Phase 1 ships as a single PR, the migration sequence should be:

1. Create `vancon_bid_breakdowns` table (new — no risk).
2. `ALTER TABLE bid_events ADD COLUMN ...` (additive — no risk).
3. `ALTER TABLE bid_results ADD COLUMN ...` (additive — no risk).
4. **No backfill required.** All new columns are nullable; existing rows get NULL. Backfill workers (job_type taxonomy, listed_subs from text re-parse, etc.) come in later phases.

This means the PR is genuinely additive and reversible — no risk to existing data, no downtime, can ship as a Render auto-deploy without a maintenance window.

---

## 7. Branch state — main vs feature/market-intel-v15

**As of 2026-05-01, last commit on each:**

```
main                          630cc31  chore(data): convert HCSS Activities.xlsx -> .xlsb
feature/market-intel-v15      84c335a  docs(agent_board): log Backend cron + Frontend slice-5 close-outs
```

**Delta:** 24+ commits on the feature branch, including all Market Intel models, ITD pipeline, Render cron, 5 frontend slices, and analytics SQL.

**Implication for Phase 1 PR:** the schema additions PR has to target **`feature/market-intel-v15`**, not main, because the base tables (`bid_events`, `bid_results`, `contractors`) only exist there. Once that branch merges to main, future Phase 1+ PRs target main.

**Pending Phase 0 → Phase 1 sequence:**

1. Land this doc on `main` (it's documentation; safe to merge before the feature branch).
2. **Decide:** merge `feature/market-intel-v15` to main now, OR keep it as a long-lived branch and target Phase 1 PR there. Recommend: merge first. Reasons:
   - The branch has been stable for days — equipment ingest verification on Render confirms the deployed state of related infrastructure is healthy.
   - 24 commits is a lot to keep diverging.
   - Phase 1 schema additions are easier to review on main than on a 24-commit-deep feature branch.
3. Phase 1 PR: targets main, single PR titled `feat(market-intel): schema additions for layer A/B forward-compat`. Adds the columns + new table per § 6a-c.

---

## 8. Document maintenance

Refresh this doc when any of the following happens:

- A new mart lands on main (add to § 1a).
- A new state DOT scraper ships (update § 4a).
- KWMF-sql credentials arrive and live Vista access opens (update § 3, run a re-introspection, update VistaSQL.md too).
- A pipeline cadence changes (update § 2).
- Any schema migration touches the Market Intel tables (update § 5).
- Phase 2-5 ships (annotate § 6 with what landed and what evolved).

Last updated: 2026-05-01 by Lead Agent. Next planned refresh: after KWMF-sql access opens or after `feature/market-intel-v15` merges to main, whichever comes first.
