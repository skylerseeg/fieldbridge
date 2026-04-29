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

| Phase | Scope | When | Branch state |
|---|---|---|---|
| **v1.5a** | Schema, scraper service, n8n cron, dark accumulation | Now → 2 weeks | This branch |
| **v1.5b** | Backfill 90 days UT/ID/NV; parser fixtures from real HTML; data validation | +2 weeks | This branch |
| **v2** | Frontend UI in `frontend/src/modules/market-intel/`: Competitor Curves, Opportunity Gaps, Bid Calibration | After 4–6 weeks of accumulation | Merge to main when v1 is locked |
| **v3** | Per-tenant overlays, multi-tenant marketing surface, predictive RFP scoring | Post-v2, when 2–3 paying tenants exist | post-merge |

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
│           ├── scrapers/napc_network/{registry,fetcher,parsers/}
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

## Risk flags

- **NAPC ToS**. Public bid results are public record, but NAPC's
  contractor directory is plausibly protected. Restrict scrape to
  bid event pages; skip `/directory/*` profile crawls. Use directory
  links only as identifiers for `contractor_resolver`.
- **Robots.txt**. NAPC is already 403-ing aggressive crawlers. The
  fetcher is robots-aware (`urllib.robotparser`), self-identifying
  (`FieldBridge-Research/1.0 (+https://fieldbridge.io/bot)`), and
  rate-limited to 1 request per 3–6 seconds per host. Do not relax
  these settings without a real reason.
- **PII**. Directory pages may contain contact emails/phones. Store
  only canonical names + bid amounts in `bid_results`. Do not
  ingest contact info from these scrapes.
- **Storage growth**. ~1,000 bid posts per state per year × 50 states
  × 5–10 bidders per post = ~250k–500k rows/year. Manageable on
  basic-256mb Postgres for v1.5. Plan a `bid_events` partition by
  `bid_open_date` quarter when row count crosses 5M.

## Worker streams

| Stream | Owns | Status |
|---|---|---|
| **Market Intel Backend Worker** | `app/services/market_intel/*`, `app/modules/market_intel/service.py` SQL fill-in, `workers/n8n_flows/market_intel_daily.json`, fixtures + tests for parsers | New stream — first task: `registry.py` probe across 50 states + parse 50 captured Idaho posts as fixtures. See brief in `app/services/market_intel/README.md`. |
| **Market Intel Frontend Worker** | `frontend/src/modules/market-intel/*` | New stream — first task: full UI per the brief in `frontend/src/modules/market-intel/PROPOSED_CHANGES.md`. Runs against `VITE_USE_MOCK_DATA=true` until backend SQL lands. |
| **Lead** | `app/main.py` route mount, `app/models/{bid_event,bid_result,contractor}`, `app/core/seed.py` shared-network bootstrap, `app/models/tenant.py` `kind` column, this doc, `docs/agent_board.md` | Scaffold landed. Reviews + merges. |

## Out of scope (this branch)

- Multi-tenant onboarding for non-VanCon contractors — v3.
- Predictive RFP scoring — v3, separate module.
- Choropleth map — v2.1.
- Export to CSV — v2.1.
- BidNet Direct integration — separate project, post-v2.
- State DOT bid tab parsers (UDOT, ITD, NDOT) — v1.5b after NAPC
  parsers stabilize.
