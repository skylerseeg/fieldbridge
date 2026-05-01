# Market Intel — design doc

**Status**: v1.5 scaffold landed on `feature/market-intel-v15`.
Implementation is in flight. Do **not** merge this branch to `main`
until the v1 deploy (Equipment + Vista mart ingest) is rock-solid.

---

## Why this exists

VanCon Inc. — and every Vista heavy-civil contractor — bids against
the same regional cast (Sunroc, Geneva Rock, Granite, Staker Parson,
Kilgore, Wadsworth, etc.) on hundreds of public solicitations per
year. Public bid results are **public record**: state DOTs publish
bid tabs; NAPC's `{state}bids.{com,net}` portals publish low-bidder
announcements with full competitor lines.

Nobody aggregates this dataset for the contractor's own seat. The
existing players (BidNet, ConstructConnect, Dodge) are pre-bid
aggregators sold to estimators looking for **opportunities**.
Post-bid analytics — "who beat me by how much, where, on what
scope?" — is a gap.

FieldBridge already owns the contractor's Vista history. Marrying
public bid network data to internal job-cost history is the
combination nobody else can ship without a Vista integration story
they've stopped investing in.

## Strategic phasing

**2026-04-29 strategic pivot — NAPC paused, State DOT primary.** See
"Data source pivot" below for the full rationale. Phasing updated:

| Phase | Scope | When | Branch state |
|---|---|---|---|
| **v1.5a** | Schema + ITD (Idaho Transportation Department) bid-tab parser + dark accumulation. NAPC scrapers paused at the registry-probe layer. | Now → 2 weeks | This branch |
| **v1.5b** | Add UDOT + NDOT bid-tab parsers (UT, NV); 90-day backfill from each DOT's published archives; data validation against Vista vendor master | +2 weeks | This branch |
| **v2** | Frontend UI in `frontend/src/modules/market-intel/`: Competitor Curves, Opportunity Gaps, Bid Calibration (already in flight; doesn't depend on data source) | After 4–6 weeks of accumulation | Merge to main when v1 is locked |
| **v3** | Per-tenant overlays, multi-tenant marketing surface, predictive RFP scoring. Possible NAPC partnership integration if outreach succeeds. | Post-v2, when 2–3 paying tenants exist | post-merge |

## Architecture

```
backend/
├── app/
│   ├── models/
│   │   ├── tenant.py            # extended with `kind` column
│   │   ├── bid_event.py         # NEW — public bid solicitation/award
│   │   ├── bid_result.py        # NEW — one row per bidder per event
│   │   └── contractor.py        # NEW — canonical entities, apvend match
│   ├── modules/
│   │   └── market_intel/        # READ API
│   │       ├── router.py        # /api/market-intel/{competitor-curves, opportunity-gaps, bid-calibration}
│   │       ├── schema.py        # Pydantic — mirrors frontend types.ts
│   │       └── service.py       # query layer
│   └── services/
│       └── market_intel/        # SCRAPER + INGEST PIPELINE
│           ├── scrapers/
│           │   ├── napc_network/   # PAUSED — see _napc_paused.md
│           │   │   ├── registry.py, state_portal_registry.json   # kept (intelligence asset)
│           │   │   └── _napc_paused.md  # robots block, pivot rationale
│           │   └── state_dot/       # ACTIVE — v1.5 primary source
│           │       ├── itd.py       # Idaho DOT — first parser
│           │       ├── udot.py      # v1.5b
│           │       └── ndot.py      # v1.5b
│           ├── normalizers/{csi_inference,contractor_resolver,geo_resolver}.py
│           ├── analytics/*.sql
│           └── pipeline.py
├── scripts/
│   └── migrate_tenants_add_kind.py   # one-shot prod migration

frontend/
└── src/
    └── modules/
        └── market-intel/        # kebab-case, matches existing modules

workers/
└── n8n_flows/
    └── market_intel_daily.json  # cron, staggered per state
```

### Why a service, not an "agent"

The `agents/` directory at repo root is reserved for **Anthropic
LLM-tool-use modules** that talk to `anthropic.Anthropic()` with
prompt caching and structured tool output. The Market Intel scraper
is plain HTTP + HTML parsing + SQL writes. It belongs in
`backend/app/services/`, alongside `email_bridge`, `vista_sync`, etc.
Naming matters because workers and reviewers grep by directory.

### Tenant scoping

Every model row has `tenant_id`. The Market Intel write path always
writes to `SHARED_NETWORK_TENANT_ID`, a deterministic UUID v5 of
`uuid5(NAMESPACE_DNS, "shared.fieldbridge.network")` =
`7744601c-1f54-5ea4-988e-63c5e2740ee3`. Customer-tenant reads union
their own ID with that sentinel.

The shared-network tenant has `kind="shared_dataset"` (new column on
`tenants` — see `migrate_tenants_add_kind.py`). Three values:

| `kind` | Meaning |
|---|---|
| `customer` | Paying contractor running Vista. Default. Appears in billing rollups + tenant switcher. |
| `shared_dataset` | Cross-tenant data namespace. Never billed, never in switcher. |
| `internal_test` | Fixtures, integration harness, dev tenants. Excluded from prod rollups. |

#### Historical tenant ID note

The deterministic VanCon UUID is
`5548b0a7-bc38-5dd2-ba4c-aef6623cee50`. The **live** prod VanCon
tenant has a random uuid4 (`7311e6ad-7203-4131-970e-cda3feff9292`)
because it was seeded before this convention existed. We leave that
row alone — rewriting it would cascade through every mart_* row via
FK and buys nothing. New deployments will use the deterministic ID.

## Navigation contract

**v1.5 / v2**: peer route at `/market-intel`. Sidebar nav entry under
the existing **Intelligence** group, between Bids and Proposals.

**v3 (potential)**: when there are 2+ intelligence modules
(Predictive PM is pseudo-intel today, Recommendations is shell-only;
neither has a moat), regroup routes under `/intelligence/{market-intel,predictive-maintenance,…}`.
That's a `routes.tsx` edit + 301 redirect rules, not a refactor.
**This is a known future move, NOT a surprise.**

## Data source pivot — 2026-04-29

**TL;DR**: NAPC's robots.txt deny-by-default is load-bearing. We
pause NAPC scraping at the registry-probe layer, pivot v1.5
primary source to State DOT bid tabulations (ITD first, UDOT/NDOT
in v1.5b), and pursue NAPC partnership in parallel as a separate
Lead/Operator workstream.

### What we found

`https://www.idahobids.com/robots.txt` (and presumably the same
across NAPC's portfolio of `{state}bids.{com,net}` portals):

```
User-agent: *
Disallow: /
```

…with an explicit allowlist of ~21 named search engines (Google,
Bing, Apple, Baidu, etc.). `FieldBridge-Research/1.0` is not on
that list. `urllib.robotparser.can_fetch()` returns False for
every URL on the host.

NAPC's policy is deliberate: named-allowlist of search engines = "we
want to be findable on Google but not scraped." Bypassing it is
inconsistent with the explicit risk-flag commitment in the original
design doc ("Do not relax these settings without a real reason").

### Decision (Lead + Operator, 2026-04-29)

| Option | Decision | Rationale |
|---|---|---|
| **A. Pivot v1.5 primary source to State DOT bid tabs** | ✅ Accepted | Government-published-as-public-record. Heavy-civil precision target (the actual subset VanCon competes for). Schema, read API, tenant scoping, frontend all unchanged. PDF parsing (pdfplumber) instead of HTML, but pdfplumber against tabular DOT data is well-trodden. |
| **B. One-time fixture-capture override for NAPC** | ❌ Rejected | "We want fixtures" isn't a real reason. Sets a bad precedent. Legal exposure (CFAA arguments are weak but expensive). Doesn't unblock the production fetcher anyway. |
| **C. NAPC partnership outreach** | ✅ Pursued in parallel | Lead/Operator-driven, not a worker dependency. Best case: API access. Realistic: "no, here's our paid product." Worst: silence. Worth pursuing because a successful outcome compounds the moat — but slice 2/3/4 do not wait on it. |

### What we kept

- `scrapers/napc_network/registry.py` and the committed
  `state_portal_registry.json` (50 states, schema_version 1) —
  intelligence asset. If outreach succeeds we have the URL map ready.
- The schema (`bid_events`, `bid_results`, `contractors`) — source-
  agnostic; ITD-sourced rows have the same shape as NAPC-sourced
  rows would have.
- The read API, frontend module, tenant scoping pattern — all
  unaffected.

### What we paused

- Live NAPC fetching at any layer. Marked at
  `scrapers/napc_network/_napc_paused.md` (worker drops this in
  slice 2-revised).
- The "1,000 bid posts × 50 states" storage estimate; State DOT
  data volume is meaningfully smaller per state (one DOT per
  state vs. dozens of municipal solicitations). New storage
  estimate locked in v1.5b after first 30 days of ITD ingest.

## Operations

### Nightly cron — dual triggers

The ITD ingest pipeline (`ITDPipeline.run_state("ID", db)`) is wired
to fire from **two** schedulers, by design. This is the option-C
decision recorded in PRs #16 (n8n piece) and the Lead-direct commit
`92ccfb3` (Render piece).

| Trigger | Path | Role | Owner |
|---|---|---|---|
| **Render Cron Job** (primary) | `backend/scripts/run_itd_pipeline.py` against the prod DB via `DATABASE_URL` | Production primary — runs nightly, no HTTP hop, ~$1/mo on starter | `fieldbridge-itd-pipeline` cron entry in `render.yaml` |
| **n8n HTTP cron** (optional, ships inactive) | `POST /api/v1/market-intel/admin/run-itd-pipeline` (gated by `require_admin`) | Ad-hoc admin runs, replay after fixture-format changes, alerting branch on anomaly counters via the IF node | `workers/n8n_flows/market_intel_daily.json` |

Both call the same `ITDPipeline` class, so DB writes are idempotent
across either trigger — the `(tenant_id, source_url, raw_html_hash)`
unique constraint dedups. In steady state Render is the primary;
n8n is intentionally inactive (`"active": false`) on import and
only flipped on if/when the Operator wants UI-driven runs +
Slack-style alerting via the IF→Webhook branch.

When deduplication is desired (e.g. one of the two paths starts
running consistently first), keep both wired — the redundant call
just reports `skipped_already_ingested = N` and exits cleanly.

#### Why both, not just one

- **Render cron is simpler, fewer moving parts, prod-primary fit.**
  No new infrastructure, no separate workflow database, env-var
  plumbing identical to the API service.
- **n8n adds observability and ad-hoc trigger UX** — IF-on-anomaly
  branch (`skipped_parse_error > 0` or `skipped_fetch_error >= 5`),
  Webhook node for Slack-style alerting, manual trigger from the
  n8n UI for replay after fixture-format changes.
- **Idempotency at the DB layer means dual triggers can't
  double-write** — the unique constraint on `bid_events` is the
  source of truth, not the schedule.

#### Activating the n8n side (post v1 lock)

The flow JSON ships with `"active": false`. To activate:

1. Import `workers/n8n_flows/market_intel_daily.json` into a
   running n8n instance (n8n.cloud or self-hosted).
2. Set the per-flow env vars (admin JWT for `Authorization`
   header, alert webhook URL — see `workers/n8n_flows/README.md`).
3. Flip the activation toggle in the n8n UI.

Until then, only the Render cron fires. The n8n flow lives in the
repo as documentation of intent + ready-to-import fallback.

## Risk flags

- **State DOT publication ToS**. State DOTs publish bid tabulations
  under transparency mandates (e.g. ITAR Title 39 / state public-
  records statutes). Scraping is generally explicitly permitted.
  Verify each DOT's robots.txt + publications page ToS at parser-
  add time and document in the parser's module docstring.
- **PDF text-layer reliability**. Most modern DOT bid tabs are
  generated reports with clean text layers. Pre-2015 archives
  may be scans; OCR via `pytesseract` (already in requirements)
  is the fallback. Flag scan-detected PDFs in the fixture
  manifest's `template_version` field.
- **NAPC robots block (paused, not solved)**. The decision above
  pauses NAPC indefinitely. If anyone — current worker, future
  worker, Lead, or Operator — proposes resuming NAPC scraping,
  read this section first. The robots block does not become less
  load-bearing because the dataset would be useful.
- **PII**. State DOT bid tabs sometimes list public-employee
  contact info (project engineer, contracting officer). Public-
  record context, but apply the same strip-then-verify regex pass
  as the original NAPC plan. Names of public employees stay (they
  ARE the public record); emails and phones are stripped.
- **Storage growth (revised)**. ~50–200 bid tabs per DOT per year
  × 5 DOTs at v1.5b × 4–8 bidders per tab = ~5k–8k rows/year for
  v1.5. Trivial on basic-256mb Postgres. Revisit when v3
  multi-tenant is live.

## Worker streams

| Stream | Owns | Status |
|---|---|---|
| **Market Intel Backend Worker** | `app/services/market_intel/*`, `app/modules/market_intel/service.py` SQL fill-in, `workers/n8n_flows/market_intel_daily.json`, fixtures + tests for parsers | Active. Slices landed: NAPC registry probe (50/50 states, paused — see Data source pivot), schema_version + agent-assert follow-ups. **Current task**: ITD bid-tab fixtures + pdfplumber parser (slice 2-revised after NAPC pivot). |
| **Market Intel Frontend Worker** | `frontend/src/modules/market-intel/*` | New stream — first task: full UI per the brief in `frontend/src/modules/market-intel/PROPOSED_CHANGES.md`. Runs against `VITE_USE_MOCK_DATA=true` until backend SQL lands. |
| **Lead** | `app/main.py` route mount, `app/models/{bid_event,bid_result,contractor}`, `app/core/seed.py` shared-network bootstrap, `app/models/tenant.py` `kind` column, this doc, `docs/agent_board.md` | Scaffold landed. Reviews + merges. |

## Registry validation

The committed `state_portal_registry.json` is built offline by
`backend/scripts/run_napc_probe.py`. The shape of that file is locked
in by `backend/tests/unit/test_market_intel_registry.py`, but the
shape test cannot tell whether the probe's network reality is
honest — only whether the JSON is well-formed. Use this list as a
post-probe smoke check.

Nine NAPC portals were manually verified during architecture discovery
on 2026-04-29 against a fresh browser:

| State | Hostname            | Variant |
|-------|---------------------|---------|
| CA    | californiabids.com  | com     |
| ID    | idahobids.com       | com     |
| UT    | utahbids.net        | net     |
| TX    | texasbids.net       | net     |
| FL    | floridabids.net     | net     |
| NV    | nevadabids.com      | com     |
| NY    | newyorkbids.net     | net     |
| NC    | northcarolinabids.com | com   |
| GA    | georgiabids.net     | net     |

After running the probe: each of these states' matching variant in
`states[XX][variant].status` MUST be one of `200`, `3xx_resolved`, or
`403_blocked`. Anything else (`404`, `dns_fail`, `ssl_error`,
`timeout`, `200_parked`, etc.) means the probe disagrees with reality
and you should investigate the probe — egress, header rejection, NAPC
change, or a regression in `registry.py` — before committing the new
registry. **Do not relax the smoke check by editing this list to match
a broken probe.**

Known apex quirks the probe has to handle (caught during the first
real run on 2026-04-29):

* `utahbids.com` returns HTTP 200 with a 114-byte JS redirect to
  `/lander` — a domain-parking page. The probe classifies that as
  `200_parked` and demotes it out of primary-variant selection;
  `utahbids.net` is the real portal.
* `idahobids.com` ships a TLS cert valid only for `www.idahobids.com`.
  The probe falls back to the `www.` host and records `via_www: true`
  on the variant entry.
* `alaskabids.com` redirects through `akbids.com` to
  `greatnorthauction.com`. The probe follows redirects and lands on
  `3xx_resolved` with the resolved final URL.
* **Massachusetts** uses `massbids.net` (43 KB live portal). The
  algorithmic stem `massachusettsbids.{com,net}` DNS-fails;
  `mabids.com` is parked. Captured as a one-off entry in
  `_STATE_STEM_OVERRIDES` inside `registry.py`. New stem exceptions
  go in that map with a date + verification note alongside the MA
  entry — not in the JSON.

Adding a new known quirk: append it here. Generic behaviors (parking
detection, redirect handling, www-fallback) belong in `registry.py`;
state-specific stem exceptions go in `_STATE_STEM_OVERRIDES` in the
same file. The committed JSON is purely the probe output and never
holds overrides.

## Out of scope (this branch)

- Multi-tenant onboarding for non-VanCon contractors — v3.
- Predictive RFP scoring — v3, separate module.
- Choropleth map — v2.1.
- Export to CSV — v2.1.
- BidNet Direct integration — separate project, post-v2.
- State DOT bid tab parsers (UDOT, ITD, NDOT) — v1.5b after NAPC
  parsers stabilize.
