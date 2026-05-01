# PROPOSED_CHANGES — Market Intel detail routes

**Author**: Market Intel Frontend Worker
**Branch**: `feat/market-intel-fe-slice-3` (raised in PR #9, follow-up clarifications carried in PR #10 alongside placeholder pages)
**Audience**: Lead Agent (`frontend/src/routes.tsx` is Lead-owned)
**Status**: ask — workers don't edit `routes.tsx` directly

---

## Why

The Competitor curves drilldown (slice 2) and the Opportunity gaps
top-10 list (slice 3) both expose buttons that `navigate()` to
detail routes that don't yet exist in `routes.tsx`. The buttons
work — they navigate — but the navigation currently hits the
catch-all 404 because the routes aren't registered. This is a known
v1.5/v2 gap and acceptable as an interim, but Lead asked for the
asks to be filed as a single PROPOSED_CHANGES.md so the route
table can be wired at any merge point.

## What's needed

Two routes under the existing `/market-intel` parent:

```tsx
// Slice 2 — contractor detail (carry-over from the slice-2 PR).
{ path: "market-intel/contractor/:slug", element: <ContractorDetailPage /> },

// Slice 3 — county-level gap detail.
{ path: "market-intel/gap/:state/:county", element: <GapDetailPage /> },
```

Both placeholder pages live under
`frontend/src/modules/market-intel/` and can be added by Lead at
route-wire time (or asked back to me — I've kept the slugify and
URL-encoding contract well-defined so the components are
straightforward to build).

## URL contracts

### Contractor detail (`/market-intel/contractor/:slug`)

Slug is built by `slugifyContractor(contractor_name)` inside
`components/CompetitorCurves.tsx`:

```ts
function slugifyContractor(name: string): string {
  return name
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}
```

Examples:
- `"Sunroc Corporation"` → `sunroc-corporation`
- `"Ralph L. Wadsworth Construction"` → `ralph-l-wadsworth-construction`
- `"Galicia's Concrete"` → `galicia-s-concrete`
- `"B Squared Legacy GC"` → `b-squared-legacy-gc`

The detail page would re-resolve the slug back to a `contractor_id`
via a `/api/market-intel/contractor/{slug}` endpoint (not yet
defined in the backend `schema.py`).

### Gap detail (`/market-intel/gap/:state/:county`)

URL is built inline in `components/OpportunityGaps.tsx`:

```ts
navigate(
  `/market-intel/gap/${row.state}/${encodeURIComponent(row.county ?? "")}`,
);
```

`row.state` is a two-letter uppercase code from the wire payload
and is URL-safe by construction. `row.county` can contain spaces
(e.g. `Salt Lake`) so it goes through `encodeURIComponent`.
React Router's `:county` param is automatically URL-decoded when
the detail page reads it via `useParams<{ state: string; county: string }>()`.

Examples:
- UT, Salt Lake → `/market-intel/gap/UT/Salt%20Lake`
- ID, Ada → `/market-intel/gap/ID/Ada`
- WY, "" (state-only row) → `/market-intel/gap/WY/`
  (the trailing slash + empty `:county` will need a route variant —
  see "Edge cases" below)

## Edge cases

1. **State-only rows.** Some `OpportunityRow`s carry `county: null`
   for state-level aggregations. The current top-10 list filters in
   only county-bearing rows by accident (because the mock fixture
   has no nulls), but the wire allows null. If the backend starts
   returning state-only rows, the detail navigation would produce
   `/market-intel/gap/UT/` which doesn't match the
   `:state/:county` pattern. Two options:
   - Add a sibling route `:state` (state-only detail page).
   - Or filter null-county rows out of the top-10 list and document.

   Recommendation: filter for v1.5; add the state-only route in v2.1
   alongside the choropleth.

2. **404 fallback — placeholder pages now ship in this module**
   (slice 4). `frontend/src/modules/market-intel/ContractorDetailPage.tsx`
   and `frontend/src/modules/market-intel/GapDetailPage.tsx` render
   a "Coming soon — bid history not implemented yet" card with the
   echoed slug or state/county, plus a Back link to `/market-intel`.
   Wiring `routes.tsx` to point at them is the only remaining step;
   until then the buttons hit the catch-all 404, which is the
   documented v1.5 interim.

## Suggested wiring location

In `routes.tsx`, the existing entry is:

```tsx
{ path: "market-intel", element: <MarketIntelPage /> },
```

The two new entries sit alongside it as siblings:

```tsx
{ path: "market-intel", element: <MarketIntelPage /> },
{ path: "market-intel/contractor/:slug", element: <ContractorDetailPage /> },
{ path: "market-intel/gap/:state/:county", element: <GapDetailPage /> },
```

If/when v3 regroups under `/intelligence/*` (per `docs/market-intel.md`),
all three move together with 301 redirects from the bare
`/market-intel/*` paths.

## No backend dependency

Wiring the routes themselves requires no backend changes —
placeholder detail pages can render against the existing list
endpoints' data filtered to the slug/state-county. A proper detail
endpoint is a separate Backend Worker ask.
