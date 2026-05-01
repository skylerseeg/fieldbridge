# Market Intel — frontend module

`Bid intelligence` — public bid-network analytics surfaced inside
FieldBridge. Owned by the **Market Intel Frontend Worker** stream;
brief lives in `PROPOSED_CHANGES.md` next to this file. Design doc:
`docs/market-intel.md`.

## Status (2026-04-29)

**Brief closed — all 4 slices merged.** The module ships the page
shell, three tabs against live + mocked data, four-state coverage
on every tab, and the `--color-good` / `--color-watch` token system.

| Slice | Scope                                                                | State |
|------:|----------------------------------------------------------------------|-------|
|     1 | Types, client, mock fixtures, hooks, page shell, KPI strip, tab stubs | done  |
|     2 | Tab 1 — Competitor curves: scatter, side-sheet drilldown, sortable table; `--color-good` / `--color-watch` token add; first per-tab vitest | done |
|     3 | Tab 2 — Opportunity gaps: grouped BarChart + top-10 list + scope-code multi-select; coral-ramp first use; per-tab vitest; route asks filed in `PROPOSED_CHANGES_routes.md` | done |
|     4 | Tab 3 — Bid calibration: dual-axis ComposedChart + most-recent-row highlight + brief-locked annotation; final per-tab vitest; placeholder ContractorDetailPage + GapDetailPage | done |

All three tabs render real visualizations against mock data (or
live API when `VITE_USE_MOCK_DATA` is unset). Empty / loading /
error / populated branches final on all three. Per-tab vitest
locks the four required states for each tab plus the slice-4
"highlight one row" assertion.

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
├── ContractorDetailPage.tsx           # placeholder for /contractor/:slug
├── GapDetailPage.tsx                  # placeholder for /gap/:state/:county
├── README.md
├── PROPOSED_CHANGES.md                # worker brief
├── PROPOSED_CHANGES_routes.md         # Lead ask: routes.tsx wiring for detail pages
├── api/
│   ├── types.ts                       # mirrors backend schema.py
│   ├── client.ts                      # axios fetchers
│   └── mockData.ts                    # fixtures + VITE_USE_MOCK_DATA
├── hooks/
│   ├── useCompetitorCurves.ts
│   ├── useOpportunityGaps.ts
│   └── useBidCalibration.ts
├── components/
│   ├── ModuleHeader.tsx               # H1 + subtitle + filter bar
│   ├── StateMultiSelect.tsx           # dropdown-menu-based state filter
│   ├── ScopeMultiSelect.tsx           # dropdown-menu-based scope-code filter
│   ├── KpiStrip.tsx                   # 4 KPI tiles, derives from datasets
│   ├── EmptyState.tsx                 # default / info / error variants
│   ├── CompetitorCurves.tsx           # tab 1 — scatter + sheet + table (slice 2)
│   ├── OpportunityGaps.tsx            # tab 2 — bars + top-10 list (slice 3)
│   └── BidCalibration.tsx             # tab 3 — composed dual-axis + table (slice 4)
└── __tests__/
    ├── CompetitorCurves.test.tsx      # 6 tests — empty/loading/error/populated × sort × drilldown
    ├── OpportunityGaps.test.tsx       # 7 tests — four states × ranking × navigation × scope filter
    └── BidCalibration.test.tsx        # 8 tests — four states × annotation × highlight × win-rate math
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

## Known follow-ups

- **Detail routes — Lead ask, see `PROPOSED_CHANGES_routes.md`**.
  Both the Competitor curves drilldown ("View bid history") and the
  Opportunity gaps top-10 list (row click) `navigate()` to detail
  paths that aren't yet wired in `routes.tsx`:
  - `/market-intel/contractor/:slug` (slice 2 ask)
  - `/market-intel/gap/:state/:county` (slice 3 ask)

  Slice 4 ships placeholder pages at `ContractorDetailPage.tsx` and
  `GapDetailPage.tsx`, so wiring is purely a `routes.tsx` edit. The
  PROPOSED_CHANGES file has the slug derivation, URL encoding rules,
  edge cases, and the copy-pasteable wiring snippet. Until wired,
  the buttons navigate to paths that hit the catch-all 404.
- **`/api/market-intel/summary` endpoint.** KPI tile 1 (`Bid events
  tracked`) currently displays `sum(bid_count)` from competitor
  curves, labelled "bid lines" — honest but approximate. A proper
  network-wide event count belongs in a backend `summary` route. The
  Backend Worker brief at
  `backend/app/services/market_intel/README.md` should add this when
  analytics SQL lands.
- **Field-mode contrast for `--color-good` / `--color-watch`.**
  `field-mode.css` (Frontend Polish's lane) re-points the existing
  semantic tokens for outdoor glare; the two Market Intel duotones
  aren't yet covered. Worth adding when the module ships into a
  field-deployed scenario; not blocking v1.5/v2 since Bid intelligence
  is an office workflow.
