# PERF AUDIT — Phase 2 baseline + chunk plan

**From**: Frontend Polish Worker (Agent #4)
**To**: Lead Agent
**Date**: 2026-04-28
**Status**: Step 1 of 4 — baseline + chunk plan, awaiting sign-off
**Tooling**: `npx vite-bundle-visualizer -t raw-data` → custom Node aggregator
(see `/tmp/analyze-bundle.mjs`); raw stats at `/tmp/bundle-stats.json`

## Vite's reported numbers (final, post-tree-shake stream gzip)

```
dist/index.html                      0.50 kB │ gzip:   0.32 kB
dist/assets/index-*.css             35.95 kB │ gzip:   7.52 kB
dist/assets/index-*.js           1,572.32 kB │ gzip: 408.17 kB │ map: 6,607.09 kB
```

One JS chunk. 2,709 modules transformed. Cold-load cost on a 4G connection
(~1 Mbps after TCP slow-start): **~3.3 seconds** of pure transfer for the
gzipped JS, plus ~0.5s for parse + ~1s for boot. Budget ~5 seconds before
the user can press anything. That's the user-pain Lead called out.

## Visualizer breakdown (per-module pre-shake gzip — relative ranking only)

> **Caveat:** rollup-plugin-visualizer reports the gzip size of each module
> in isolation, summed. Total comes out to **942.7 kB gzip** vs. Vite's
> **408 kB** final. The 2.3× gap is tree-shake + minify + final-stream
> recompression. Use these % shares to **rank** what to split, not to
> predict absolute savings.

### Top weight centers

| Rank | Package | Gzip (kB)\* | % share | Modules | Where in src/ |
|------|---------|-------------|---------|---------|---------------|
| 1 | `recharts` | 197.88 | 21.0% | 193 | 14 module pages + 3 dashboard cards |
| 2 | `_app/modules` (all 17 routes' code) | 106.61 | 11.3% | 31 | `src/modules/*` |
| 3 | `@azure/msal-browser` | 91.61 | 9.7% | 53 | `Root.tsx`, `LoginPage.tsx`, `lib/msal.ts` |
| 4 | `@azure/msal-common` | 81.28 | 8.6% | 61 | (transitive of msal-browser) |
| 5 | `react-dom` | 42.00 | 4.5% | 6 | bootstrap |
| 6 | `@remix-run/router` | 41.06 | 4.4% | 1 | (transitive of react-router) |
| 7 | `axios` | 39.30 | 4.2% | 50 | `lib/api.ts` + msal interceptor path |
| 8 | `lucide-react` | 29.87 | 3.2% | 104 | sidebar, topbar, every module page |
| 9 | `_app/components` | 24.06 | 2.6% | 28 | `src/components/*` (shell + dashboard + ui) |
| 10 | `@tanstack/query-core` | 19.37 | 2.1% | 18 | `lib/queryClient.ts` |
| 11 | `es-toolkit` | 18.99 | 2.0% | 106 | (transitive — likely via recharts; not a direct dep) |
| 12 | `@tanstack/table-core` | 18.94 | 2.0% | 1 | 13 module pages via react-table |
| 13 | `@radix-ui/react-slot` | 16.77 | 1.8% | 16 | shadcn primitives |
| 14 | `decimal.js-light` | 12.88 | 1.4% | 1 | (transitive of recharts) |
| 15 | `tailwind-merge` | 12.15 | 1.3% | 1 | `lib/utils.ts` (cn() helper) |

\* Pre-shake module gzip; not directly comparable to Vite's 408 kB final.

### Recharts ecosystem total

`recharts` (197.88) + `decimal.js-light` (12.88) + `_app/curve` (4.42, d3
curves) + `_app/color.js` (3.61, d3-color) + `eventemitter3` (2.40) +
`es-toolkit` overhead = **~221 kB pre-shake**. Single largest weight
center in the bundle.

### MSAL ecosystem total

`@azure/msal-browser` (91.61) + `@azure/msal-common` (81.28) +
`@azure/msal-react` (2.50) = **~175 kB pre-shake**. Currently
**eager-loaded** because `Root.tsx` and `LoginPage.tsx` use static
`import { ... } from "@azure/msal-react"` at the top of the file —
even though the runtime conditionally skips MSAL via `isMsalConfigured`.
Tenants without Azure SSO configured pay the full MSAL cost on every
cold load.

## Specific import flags

1. **`@azure/msal-*` is statically imported** at module top-level in
   `Root.tsx` (`import { MsalProvider } from "@azure/msal-react"`) and
   in `LoginPage.tsx` (`import { useMsal } from "@azure/msal-react"`).
   The `lib/msal.ts` module is also static. The `isMsalConfigured`
   gate runs at runtime, but tree-shaking can't eliminate the chain
   because the imports are reachable. **Easy dynamic-import win:
   ~175 kB pre-shake out of the boot path.** Different from Recharts
   (which is genuinely needed by the home dashboard) — MSAL is only
   needed at login time, and on tenants that even have it configured.

2. **`@tanstack/react-table`** is imported by **13** of the 17 module
   pages — every list-bearing route. Once those routes are
   `React.lazy()`'d, react-table moves with them by default. No
   special config needed; the manual chunk strategy just decides
   whether to keep it in each route's chunk or hoist it to a shared
   `vendor-tables` chunk.

3. **`recharts`** is imported by **14** module pages + **3** dashboard
   cards (`PerformanceCard`, `AgentAlertsCard`, `FleetInsightsCard`).
   Because the dashboard cards are on the home/landing route (which
   should NOT be lazy per Lead's directive), Recharts must remain
   reachable on first load. **It can still go into a separate vendor
   chunk** for cacheability across deploys, but it can't be hidden
   behind a route boundary.

4. **`lucide-react`** — 104 modules in the bundle, but the per-icon
   chunking is already happening (each named import is a separate
   module). When module routes lazy-load, their icon imports follow
   automatically. No special handling needed.

## Target chunk graph

Per Lead's "< 20 kB gzip not worth the HTTP overhead" rule, the chunks
below are sized in **estimated final gzip** (post-shake, ~43% of the
visualizer's pre-shake number based on the 408/942 ratio).

| Chunk | Contents | Est. final gzip | Why split |
|-------|----------|-----------------|-----------|
| `index.js` (entry) | bootstrap, router setup, AppShell, dashboard home, common components | ~120 kB | The minimum to render the landing page |
| `vendor-react` | `react`, `react-dom`, `react-router`, `react-router-dom`, `@remix-run/router` | ~38 kB | Stable across deploys; cache once, reuse forever |
| `vendor-charts` | `recharts`, `decimal.js-light`, `d3-color`, `d3-shape` (curves) | ~95 kB | Single biggest dep; isolating it caches well across deploys (recharts version rarely bumps) |
| `vendor-radix` | `@radix-ui/*`, `@floating-ui/*`, `react-remove-scroll` | ~30 kB | Shared across many shadcn primitives; cache stable |
| `vendor-query` | `@tanstack/react-query`, `@tanstack/query-core`, `@tanstack/react-table`, `@tanstack/table-core` | ~22 kB | Combined to clear the 20 kB threshold |
| `vendor-auth` (LAZY) | `@azure/msal-browser`, `@azure/msal-common`, `@azure/msal-react` | ~75 kB | Dynamic import behind `isMsalConfigured` check + on `LoginPage` mount |
| 17× route chunks | One per `src/modules/<name>/<Page>.tsx` plus that module's local components | 5-25 kB each | Most users hit 1-2 routes per session |

**Chunks deliberately NOT created** (under 20 kB gzip threshold):
- Standalone `vendor-axios` chunk (~17 kB) — inlined into the entry, used by every route's queries.
- Standalone `vendor-icons` (lucide) — already auto-shaken per icon.
- Standalone `vendor-tailwind` (tailwind-merge + clsx) — ~7 kB combined, inline.

## Estimated initial-load delta

Today: **408 kB gzip** (single chunk).

Phase 2 target after manual chunks + lazy routes:

| Chunk on initial home-page load | Est. gzip |
|-----|-----|
| `index.js` (entry + AppShell + dashboard home + common UI) | ~120 kB |
| `vendor-react` | ~38 kB |
| `vendor-charts` (because home dashboard uses it) | ~95 kB |
| `vendor-radix` | ~30 kB |
| `vendor-query` | ~22 kB |
| **Initial total (gzip)** | **~305 kB** |

`vendor-auth` (~75 kB) deferred behind `isMsalConfigured` dynamic import.
Module-route chunks (~50-100 kB total deferred) load on navigation, not
boot.

**Expected reduction: 408 → 305 kB initial gzip = 25% on home, 50%+ on
non-home cold-loads.**

> **Honesty caveat for Lead**: 25% home-route reduction is **below the
> 30% halt threshold** Lead set. The reason: home dashboard uses
> Recharts, so the 95 kB chart-vendor stays in the initial-load path no
> matter how I chunk it. The 50%+ reduction lands when the user's first
> destination is NOT the home dashboard (e.g. a deep-link to
> `/equipment` or `/work-orders` skips the chart-vendor entirely).

**If Lead wants stricter on the home route**, two options not in this
audit's scope:

1. **Lazy-load the dashboard chart cards.** Wrap `PerformanceCard`,
   `AgentAlertsCard`, `FleetInsightsCard` each in their own `React.lazy()`
   inside the home route. Charts render in a Suspense fallback, then
   stream in. Pushes Recharts out of the critical path; home renders the
   chrome + KPI strip immediately, charts hydrate after. Adds ~200 ms of
   "chart skeleton flash" but gets initial-load to ~210 kB gzip = 48%
   reduction. **Worth a follow-up Phase 2.5 if you want to push past 30%
   on home.**

2. **Replace Recharts.** Lead explicitly said no. Honoring that.

## Sequencing for Step 2 (your sign-off pending)

If sign-off lands as-is on the chunk plan, Step 2 is a single edit to
`vite.config.ts`:

```ts
build: {
  outDir: "dist",
  sourcemap: true,
  rollupOptions: {
    output: {
      manualChunks: {
        "vendor-react": [
          "react", "react-dom",
          "react-router", "react-router-dom",
          "@remix-run/router",
        ],
        "vendor-charts": ["recharts", "decimal.js-light"],
        "vendor-radix": [
          "@radix-ui/react-avatar", "@radix-ui/react-dialog",
          "@radix-ui/react-dropdown-menu", "@radix-ui/react-scroll-area",
          "@radix-ui/react-separator", "@radix-ui/react-slot",
          "@radix-ui/react-switch", "@radix-ui/react-tabs",
          "@radix-ui/react-tooltip",
        ],
        "vendor-query": [
          "@tanstack/react-query", "@tanstack/react-table",
        ],
      },
    },
  },
},
```

Note: I'm using the **object form** of `manualChunks` (not the function
form). Object form is enough for top-level package splitting; function
form would only be needed if I wanted dynamic per-module decisions.
Simpler diff, simpler rollback.

`d3-*`, `@floating-ui/*`, `@tanstack/query-core`, `@tanstack/table-core`,
and `@radix-ui/*-internal` packages don't need explicit listing — Rollup
will follow them transitively into whichever chunk imports them first.
The five entries above are the **public package boundaries** that
matter.

## Sequencing for Step 3 (Lead-owned commit, you spec)

Once Step 2 ships, I'll drop a `frontend/src/PROPOSED_CHANGES_routes.md`
with:

- Exact `React.lazy()` shape for each route using the named-export shim
  (no module-side refactor).
- The Suspense fallback pattern Lead specified (pulse-rectangles, not a
  designed skeleton — Phase 3 replaces them in one find/replace).
- Routes that should NOT lazy-load: `/dashboard` (home), `/login`
  (pre-auth, currently outside `RequireAuth`).
- Whether `vendor-auth` (MSAL) gets dynamic-imported via the `Root.tsx`
  / `LoginPage.tsx` change — that's a Frontend-Polish-lane edit since
  `Root.tsx` is in my lane (created by Phase 1 lint cleanup).

## Open questions for Lead

1. **MSAL dynamic import (~75 kB initial-load saving).** This is in
   `Root.tsx` (my file) and `LoginPage.tsx` (Lead-owned in `pages/`).
   I'd land the `Root.tsx` change in this brief and PROPOSED_CHANGES
   the `LoginPage.tsx` change to you. Approved as part of Step 2, or
   defer to a Phase 2.5?

2. **Home-route chart lazy-loading (~95 kB further saving).** Reaches
   the 50%+ home-route target Lead wants. Adds Suspense complexity to
   3 dashboard cards + ~200 ms perceived chart-load delay. Phase 2 or
   Phase 2.5?

3. **`vendor-react` cache-stability bonus.** Pulling `react`,
   `react-dom`, `react-router*`, `@remix-run/router` into one stable
   vendor chunk means a single cache entry that survives most deploys
   (we don't bump React versions often). Worth flagging for the user-
   facing perf story even though the gzip number on first deploy is
   unchanged.

## What I have NOT done in this audit

- No `vite.config.ts` edits (Lead's "don't open the vite config until
  sign-off" rule).
- No source-side import refactors. Every change in Step 2/3 is
  config-side; module-side imports stay as they are.
- No swap-out of any package (Recharts stays — Lead's directive).
- No `<link rel="prefetch">` aggressive preloading (Lead's directive).

## Verification artifacts

- Raw visualizer JSON: `/tmp/bundle-stats.json` (1.7 MB, persistent)
- Per-package roll-up: `/tmp/analyze-bundle.mjs` (script, idempotent)
- Treemap visualization: `/tmp/bundle-stats.html` (1 MB, openable in
  any browser)
- Vite build output: `dist/` (current)

Ready for sign-off on the chunk plan. On approval I open Step 2 with
the `manualChunks` config + a fresh build to confirm the chunk graph
materializes as predicted, then re-baseline.
