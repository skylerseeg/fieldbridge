# Market Intel service

Public bid-network ingest pipeline. Owned by the **Market Intel
Backend Worker** stream (per `docs/agent_board.md`).

## What lives here

```
market_intel/
├── scrapers/
│   ├── _base.py                   # ABCs: Fetcher, PostParser, Pipeline
│   └── napc_network/              # statebids.{com,net} portals (NAPC)
│       ├── registry.py            # state -> URL probe
│       ├── fetcher.py             # rate-limited, robots-aware HTTP
│       └── parsers/
│           └── bid_post.py        # 'low bidder' announcement parser
├── normalizers/
│   ├── csi_inference.py           # reuses email_bridge keyword map
│   ├── contractor_resolver.py     # rapidfuzz + apvend matcher
│   └── geo_resolver.py            # county/state normalization
├── analytics/                     # SQL templates returned by the read API
│   ├── competitor_curves.sql
│   ├── opportunity_gaps.sql
│   └── bid_calibration.sql
└── pipeline.py                    # run_state(state, db) orchestrator
```

## What does NOT live here

- **HTTP routes**: `backend/app/modules/market_intel/router.py` (read API)
- **Pydantic types**: `backend/app/modules/market_intel/schema.py`
- **Frontend**: `frontend/src/modules/market-intel/`
- **n8n cron**: `workers/n8n_flows/market_intel_daily.json`

## Tenant scoping

Writes go to `tenant_id = SHARED_NETWORK_TENANT_ID` (defined in
`app/core/seed.py`). Reads from the module router union the caller's
tenant with that sentinel. **Never write rows under a customer
tenant_id from a scraper.** The shared dataset is the moat; per-tenant
overlays for custom canonical names, manual apvend mappings, etc. are
a v3 follow-on.

## Lane discipline

This service is built on the `feature/market-intel-v15` branch. Do
**not** merge to `main` until v1 deploy (Equipment + Vista mart
ingest) is rock-solid, per the agent_board entry. The branch can run
alongside main for weeks; auto-deploy on Render only fires from main.

## Worker first tasks

1. Probe `registry.py` across all 50 states; commit
   `state_portal_registry.json` with the live `.com`/`.net` map.
2. Stand up `scrapers/napc_network/parsers/bid_post.py` against 50
   captured Idaho posts as fixtures (no live scraping in CI).
3. Wire `pipeline.run_state("UT")` end-to-end against the dev DB.
4. When that's clean, fill in the three `analytics/*.sql` templates
   and remove the stub returns in `app/modules/market_intel/service.py`.
5. Drop the n8n cron flow at
   `workers/n8n_flows/market_intel_daily.json`.

### Registry validation (post-probe smoke check)

Nine NAPC portals were manually verified during architecture discovery
on 2026-04-29: see `docs/market-intel.md` -> "Registry validation". If
the probe disagrees with that list, investigate the probe (network
egress, header rejection, NAPC change) before trusting the new
registry. The list is documented in the design doc, not in the test —
CI must not depend on a manual list.
