# Market Intel — frontend module

`Bid intelligence` — public bid-network analytics surfaced inside
FieldBridge. Owned by the **Market Intel Frontend Worker** stream;
brief lives in `PROPOSED_CHANGES.md` next to this file. Design doc:
`docs/market-intel.md`.

## Status (2026-04-29)

**Slice 1 of 4 landed.** Module skeleton + plumbing + KPIs.

| Slice | Scope                                                                | State |
|------:|----------------------------------------------------------------------|-------|
|     1 | Types, client, mock fixtures, hooks, page shell, KPI strip, tab stubs | done  |
|     2 | Tab 1 — Competitor curves: scatter chart, side-sheet drilldown, table | next  |
|     3 | Tab 2 — Opportunity gaps: bars + top-10 list + scope filter          | after |
|     4 | Tab 3 — Bid calibration: dual-axis chart + table; `--color-good` /<br> `--color-watch` token add; CSS bundle delta in PR description | after |

The three tabs already render against real data fetches (or mocks);
they currently show "lands in slice N" placeholders inside the
populated branch while the empty / loading / error branches are
final. Swapping the placeholder for the real chart in subsequent
slices is purely additive.

## API contract

All three endpoints live at `/api/market-intel` (note the hyphen in
the URL — the Python package uses an underscore). Backend mirrors
this module exactly via `backend/app/modules/market_intel/schema.py`;
keep the two in sync.

| Endpoint                  | Query params                                  | Returns                  |
|---------------------------|-----------------------------------------------|--------------------------|
| `GET /competitor-curves`  | `states=UT,ID&months_back=36&min_bids=10`     | `CompetitorCurveRow[]`   |
| `GET /opportunity-gaps`   | `bid_min=250000&bid_max=5000000&months_back=24` | `OpportunityRow[]`     |
| `GET /bid-calibration`    | `contractor_name_match=van%20con`             | `CalibrationPoint[]`     |

Wire-shape sources of truth live in
[`api/types.ts`](./api/types.ts).

## Mock-data toggle

Set `VITE_USE_MOCK_DATA=true` in your `.env.local` (or
`fieldbridge/.env`) to bypass the live HTTP client and serve the
fixtures in `api/mockData.ts`. The flag is inlined at build time, so
the unused branch is tree-shaken in production bundles.

```bash
# fieldbridge/frontend/.env.local
VITE_USE_MOCK_DATA=true
```

The mock fetchers honor the same param shapes as the live client, so
flipping back to real data in any single hook is a one-line edit.

## File layout

```
frontend/src/modules/market-intel/
├── MarketIntelPage.tsx                # route entry — page shell + lazy tabs
├── README.md
├── PROPOSED_CHANGES.md                # worker brief
├── api/
│   ├── types.ts                       # mirrors backend schema.py
│   ├── client.ts                      # axios fetchers
│   └── mockData.ts                    # fixtures + VITE_USE_MOCK_DATA
├── hooks/
│   ├── useCompetitorCurves.ts
│   ├── useOpportunityGaps.ts
│   └── useBidCalibration.ts
└── components/
    ├── ModuleHeader.tsx               # H1 + subtitle + filter bar
    ├── StateMultiSelect.tsx           # dropdown-menu-based multi-select
    ├── KpiStrip.tsx                   # 4 KPI tiles, derives from datasets
    ├── EmptyState.tsx                 # default / info / error variants
    ├── CompetitorCurves.tsx           # tab — slice 2 will land the chart
    ├── OpportunityGaps.tsx            # tab — slice 3 will land the chart
    └── BidCalibration.tsx             # tab — slice 4 will land the chart
```

## Adding a new tab

1. Add the tab component under `components/<Name>.tsx`. Default-export
   it so `MarketIntelPage` can `React.lazy` it. Pattern: thin shell
   with `EmptyState`-driven empty / error branches and a Recharts
   render in the populated branch. Keep the data fetch in a hook.
2. If the tab needs new wire data, add the response shape to
   `api/types.ts`, the live fetcher to `api/client.ts`, and a mock
   fixture to `api/mockData.ts`. The mock fetcher must honor the
   same param shape as the live one.
3. Add a hook in `hooks/use<Name>.ts` mirroring the existing three —
   namespaced query key, 5-minute stale time, mock toggle via
   `USE_MOCK_DATA`.
4. Wire the tab into `MarketIntelPage.tsx`: add a `<TabsTrigger>`
   under the existing list, add a `<TabsContent>` block with a
   `Suspense` wrapper, and lazy-import the component.
5. Add a Vitest file under `__tests__/<Name>.test.tsx` covering the
   four states (empty / loading / error / populated). The setup file
   in `frontend/src/test/setup.ts` already shims everything Radix
   needs.

## Tenant scoping note

This module is tenant-aware on the backend — queries union the
caller's `tenant_id` with the shared-network sentinel
(`7744601c-1f54-5ea4-988e-63c5e2740ee3`). The frontend doesn't pass
a tenant id; the JWT carries it. Auth refresh is handled by the
shared `lib/api.ts` interceptor.

## Known follow-ups (out of slice 1)

- **`/api/market-intel/summary` endpoint.** KPI tile 1 (`Bid events
  tracked`) currently displays `sum(bid_count)` from competitor
  curves, labelled "bid lines" — honest but approximate. A proper
  network-wide event count belongs in a backend `summary` route. The
  Backend Worker brief at
  `backend/app/services/market_intel/README.md` should add this when
  analytics SQL lands.
- **Detail routes.** Slice 2/3 will `navigate()` to
  `/market-intel/contractor/${slug}` and
  `/market-intel/gap/${state}/${county}`. Those routes aren't wired
  in `routes.tsx` (Lead-owned). A `PROPOSED_CHANGES.md` ask will
  ship with the relevant slice.
- **Token additions.** Slice 4 adds `--color-good` and
  `--color-watch` to `index.css` + `tailwind.config.ts` per the
  brief, mirroring the Frontend Polish worker's `field-mode.css`
  pattern. Out of slice 1 scope.
