# PROPOSED_CHANGES — Topbar INP attribution

**Author**: Market Intel Frontend Worker
**Branch**: `feat/market-intel-fe-slice-5-perf` (raised in PR #17)
**Audience**: Frontend Polish Worker (`components/shell/*` is their lane)
**Status**: ask — workers don't edit each other's lanes

---

## Why

Operator captured Web Vitals Interaction Timing on the Vercel
preview of `/market-intel`:

```
INP: 207.5 ms       ("needs improvement" — "good" is ≤ 200 ms)
Slowest element:    span.truncate, 170.1 ms render attribution
```

The capture was on the BACKEND-ERROR state of the Market Intel
page (`VITE_USE_MOCK_DATA` was unset → all three tabs rendered the
"Couldn't load …" empty/error frames, very little market-intel-
specific render work happening). The fact that `span.truncate` was
the slowest element on a page where the module renders almost
nothing is the strongest signal that the cost lives in the
**topbar**, not the module body.

## The element

`frontend/src/components/shell/TenantSwitcher.tsx:32`:

```tsx
<span className="flex max-w-[160px] items-center gap-1 truncate text-lg font-semibold tracking-tight lg:max-w-none">
  {user.tenant.name}
  <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
</span>
```

Identifying signals:
- This is the **only** `span.truncate` element in `components/shell/*`
  with `text-lg` — every other shell-truncate span is `text-sm` or
  `text-xs`.
- The `max-w-[160px] truncate lg:max-w-none` shape comes directly
  from your density-patch (`6e342db`, agent_board entry
  2026-04-28).
- The topbar renders on **every** page in the app via `AppShell`,
  so this would explain why the cost shows up regardless of which
  module is mounted.

Sibling shell elements that may also contribute:
- `Sidebar.tsx:88` — nav-item label spans (`<span class="truncate">`).
  17 nav items in 5 groups, all with truncate. Each one's parent
  re-renders on route change.
- `Topbar.tsx:131` and `Topbar.tsx:140` — user-info spans.

## What I'd want investigated

The brief asks the Frontend Polish lane to audit the topbar render
path. Specific questions a profiler trace can answer:

1. **Is `TenantSwitcher` re-rendering more than it needs to?** It
   subscribes to `useAuth((s) => s.user)`. If the auth store
   notifies subscribers on shape-stable state changes (e.g., a
   token refresh that returns the same user object), each refresh
   could trigger a re-render. Worth checking `useAuth`'s selector
   equality.
2. **Is the `flex + truncate + max-w-[160px] + nested ChevronDown
   inside a flex container without min-w-0` combination forcing a
   re-layout cascade?** Truncation is normally cheap. 170 ms of
   render attribution to a single span suggests the parent's
   layout chain is doing the work and the leaf is just where
   timing-attribution lands.
3. **Do all 17 `Sidebar.tsx` nav-item truncate spans contribute?**
   If profiler shows the cost is spread across `Sidebar` rather
   than concentrated on `TenantSwitcher`, that's a different fix
   shape (memoize nav-item rows, or reconsider whether truncate
   is needed when items wrap to two lines anyway).

## Cross-baseline ask

To confirm shell-wide vs market-intel-specific:

1. Operator captures Interaction Timing on `/equipment` on the
   same Vercel preview. If that page also shows `span.truncate`
   in the 150–200 ms range, it's confirmed shell-wide.
2. If `/equipment` is clean (sub-50 ms span renders), the cost is
   somehow specific to `/market-intel` — at which point I'd need
   to revisit my memoization pass and dig deeper. Less likely
   given the error-state capture provenance, but worth ruling
   out.

## What I've already done in my lane (PR #17)

I applied a memoization pass inside `frontend/src/modules/market-intel/*`
that's safe and correct regardless of whether the topbar work is
addressed:

- `React.memo` on the three chart wrappers (`ScatterPanel`,
  `BarPanel`, `ChartPanel`) — Recharts `ResponsiveContainer` is a
  known re-layout offender on parent re-render.
- `React.memo` on the heavy table wrappers (`CompetitorTable`,
  `CalibrationTable`) and the top-10 list (`TopList`).
- `React.memo` on the static legend / annotation components
  (`RampLegend`, `CoralLegend`, `Annotation`) and the four
  `KpiCard` instances.
- `useCallback` on the three `CompetitorCurves` callbacks
  (`toggleSort`, `handleScatterSelect`, `handleSheetOpenChange`)
  so the memoized children's reference equality holds.

These help when `MarketIntelPage`'s filter state changes (which
changes the `states: string[]` reference and propagates a re-
render down the tree) — memoized leaves now skip when their data
hasn't moved. They do **not** help with `span.truncate` because
that element is in your lane.

## No backend dep

The fix is entirely in `components/shell/*` (or the auth store's
selector equality, which is `lib/auth.ts` — Lead's lane if it
turns out to be the cause). No backend changes.

## Severity / scheduling

INP at 207.5 ms is in the "needs improvement" band, not "poor"
(>500 ms). The user-visible impact is mild — interactions feel
slightly sluggish on first paint and after auth refresh, but
nothing breaks. **Not a release blocker.**

Reasonable scheduling: pick this up alongside whatever your next
beat is. If Operator does the cross-baseline capture first and
confirms `/equipment` is also slow, my recommendation order:

1. Fix `useAuth` selector equality if profiler shows
   `TenantSwitcher` re-rendering frequently (cheapest fix, biggest
   impact).
2. Audit Sidebar nav-item rendering — `React.memo` on
   `SidebarItem` if profiler shows the cost is there.
3. Re-test INP — should drop below 200 ms.

If I can help (provide a profiler-trace screenshot, do a code
walk on `useAuth.ts`, or rerun captures), ping. Otherwise standing
down on the perf ask after PR #17 lands.
