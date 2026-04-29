# Market Intel Frontend — Worker Brief

**Owner**: Market Intel Frontend Worker (new stream — see
`docs/agent_board.md`).
**Branch**: `feature/market-intel-v15` (this branch).
**Reads**: `docs/market-intel.md` for design rationale and the v1.5/v2/v3
phasing.

---

## Stack & conventions (do not deviate)

- **React 18 + TypeScript + Vite** — locked. Do not introduce Next.js.
- **Tailwind CSS** for all styling. No CSS modules, no styled-components.
- **shadcn/ui primitives — local copy** at `frontend/src/components/ui/`.
  Reuse what's there (`Card`, `Tabs`, `Table`, `Badge`, `Button`,
  `Select`, `Input`, `Tooltip`, `Sheet`). If a primitive is missing,
  add it under that path following the existing pattern (see
  `components/ui/sheet.tsx` from the Frontend Polish Worker for the
  template).
- **Recharts** for all visualizations.
- **TanStack Query** (`@tanstack/react-query`) — already wired
  globally. 5-minute stale time per hook.
- **Lucide React** icons.
- **Vitest + Testing Library** for component tests (Storybook is **not**
  wired in this codebase; locking states via Vitest + happy-dom is the
  established pattern — see `frontend/src/components/__tests__/`).
- File location: `frontend/src/modules/market-intel/` (kebab-case;
  matches `work-orders`, `cost-coding`, etc.).
- Route path: `/market-intel`. Already wired in `routes.tsx` (lazy
  import of `MarketIntelPage`) — your job is to make that import
  resolve.

## Module structure

```
frontend/src/modules/market-intel/
├── MarketIntelPage.tsx                # default export — route entry, page shell + tabs
├── components/
│   ├── ModuleHeader.tsx
│   ├── KpiStrip.tsx
│   ├── CompetitorCurves.tsx
│   ├── OpportunityGaps.tsx
│   ├── BidCalibration.tsx
│   ├── StateMultiSelect.tsx
│   └── EmptyState.tsx
├── api/
│   ├── client.ts
│   ├── types.ts                       # mirror backend schema.py exactly
│   └── mockData.ts
├── hooks/
│   ├── useCompetitorCurves.ts
│   ├── useOpportunityGaps.ts
│   └── useBidCalibration.ts
├── __tests__/
│   ├── CompetitorCurves.test.tsx      # empty / loading / error / populated
│   ├── OpportunityGaps.test.tsx
│   └── BidCalibration.test.tsx
└── README.md
```

## API contracts (already wired backend-side, returning empty `[]` until
analytics SQL lands)

```ts
// api/types.ts — must mirror backend/app/modules/market_intel/schema.py

export interface CompetitorCurveRow {
  contractor_name: string;
  bid_count: number;
  avg_premium_over_low: number;  // 0.05 = 5% above low bid
  median_rank: number;
  win_rate: number;              // 0–1
}

export interface OpportunityRow {
  state: string;
  county: string | null;
  missed_count: number;
  avg_low_bid: number;
  top_scope_codes: string[];
}

export interface CalibrationPoint {
  quarter: string;     // ISO date, first day of quarter
  bids_submitted: number;
  wins: number;
  avg_rank: number;
  pct_above_low: number | null;
}

// Endpoints (live, returning [] until pipeline accumulates):
// GET /api/market-intel/competitor-curves?states=UT,ID&months_back=36&min_bids=10
// GET /api/market-intel/opportunity-gaps?bid_min=250000&bid_max=5000000&months_back=24
// GET /api/market-intel/bid-calibration?contractor_name_match=van%20con
```

## Page shell (`MarketIntelPage.tsx`)

Match the Cost Coding / Equipment page weight:

- Page title `Bid intelligence` (h1, ~28px, weight 500). Note: title
  is sentence case, not Title Case.
- Subtitle: `Public bid intelligence across the western network. Pricing curves, missed opportunities, and self-calibration against the low bid.`
- Filter bar (right-aligned): state multi-select (default: UT, ID, NV,
  WY, CO, AZ), months-back select (12/24/36, default 36).
- KPI strip below header — 4 cards:
  1. **Bid events tracked** — count, last 36 months
  2. **Active competitors** — distinct contractors with ≥10 bids
  3. **VanCon win rate** — % of bids submitted that won
  4. **Median premium over low** — % VanCon's losing bids ran above
     the winner
- Tabs below KPIs: `Competitor curves` · `Opportunity gaps` · `Bid calibration`
- Each tab is its own component, lazy-loaded via `React.lazy` +
  `Suspense`.

## Tab 1 — Competitor curves

Thesis: every competitor has a pricing personality. Show it.

- **ScatterChart** (Recharts): x = `median_rank` (1 = always low),
  y = `avg_premium_over_low` (%). Dot per competitor; dot size scaled
  by `bid_count`. Click a dot → side `Sheet` slides in with that
  contractor's full row + `View bid history` button (`navigate(/market-intel/contractor/${slug})`).
- Color logic: dots colored by `win_rate` using a teal ramp (light
  teal = low rate, dark teal = high). **Two color ramps max on the
  page** — teal for "active/good", coral for "watch this", gray
  structural.
- Below the scatter: sortable Table with columns: Contractor · Bids ·
  Median rank · Avg premium · Win rate. Rows clickable.
- Empty state: "Not enough bid history yet. Pipeline ingests new
  awards nightly."

## Tab 2 — Opportunity gaps

Thesis: VanCon competes on a fraction of the work it could win.
Surface the gaps.

- Left: BarChart grouped by state, each bar = one county, height =
  `missed_count`. Hover shows county + avg low bid + scope codes.
  (Choropleth is v2.1; grid bar chart is fine for now.)
- Right: top-10 list — counties ranked by `missed_count`, with avg
  low bid and CSI codes as Badges. Click a row →
  `navigate(/market-intel/gap/${state}/${county})`.
- Filter: scope-code multi-select that intersects with VanCon's
  historical scopes (default: all VanCon scopes).

## Tab 3 — Bid calibration

Thesis: VanCon needs to know whether its pricing is sharpening or
drifting.

- ComposedChart (dual-axis): x = quarters (last 8). Bars =
  `bids_submitted` (gray, left axis). Line 1 = `wins` (teal, left
  axis). Line 2 = `pct_above_low * 100` (coral, right axis, %).
- Below: calibration Table — quarter, bids, wins, win rate, avg rank,
  pct above low. Highlight the most recent quarter row.
- Annotation above the chart: `Lower coral = sharper pricing. Higher teal = more wins. Watch them move together.`

## Visual rules

- **No emoji anywhere.**
- **Sentence case** for every label, button, tab.
- **Two color ramps max:** teal for good/active signals, coral for
  watch-this signals, gray for neutral. Add semantic tokens to
  `tailwind.config.ts` (`--color-good`, `--color-watch`) — match the
  pattern Frontend Polish Worker established with `field-mode.css`.
- Money: `Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })`.
- Percentages: 1 decimal place (`12.3%`).
- Loading: skeleton boxes matching final layout — never spinners on KPI cards.
- Error: inline banner at top of tab content, "Couldn't load <view>. Pipeline may be paused — try again or check the worker status."
- Dark mode: use `bg-card`, `text-foreground`, etc. — no hardcoded
  white/black.

## Mock data

Build `mockData.ts` with realistic fixtures:

- 18 competitors including: Sunroc Corporation, Geneva Rock, Granite
  Construction, Staker Parson, Whitaker Construction, Kilgore
  Companies, Wadsworth Brothers, HK Contractors, Depatco, Galicia's
  Concrete, B Squared Legacy GC, Wheeler Machinery, Mountain Region
  Constructors, plus 5 plausible others. Bid counts 12–180. Median
  ranks 1.4–4.8. Premiums 0.5%–18%. Win rates 0.05–0.42.
- 30 opportunity-gap rows across UT/ID/NV/WY/CO/AZ counties.
  Missed counts 3–24.
- 8 quarters of calibration data, 12–28 bids/quarter, 1–9 wins,
  pct_above_low between 0.8% and 11%.

Use mock data when `import.meta.env.VITE_USE_MOCK_DATA === 'true'`;
otherwise hit the real API.

## Acceptance criteria

- [ ] Route renders at `/market-intel` and appears in left nav under
  "Intelligence" between Bids and Proposals (already wired in
  `nav-config.tsx` and `routes.tsx`)
- [ ] All three tabs render without console errors against mock data
- [ ] State filter and months-back filter both refetch all three tabs
- [ ] Tab content is lazy-loaded (React.lazy + Suspense)
- [ ] Every chart has empty/loading/error states
- [ ] Accessibility: every interactive element keyboard-reachable,
  every chart has aria-label, every color-coded value has a non-color
  secondary cue (number, badge text)
- [ ] No `any` types in `api/`, `hooks/`, or `types.ts`
- [ ] TypeScript strict mode passes (`npm run typecheck`)
- [ ] Vitest tests pass (`npm test`) — empty/loading/error/populated
  state per tab
- [ ] `npm run lint` green (no new warnings)
- [ ] CSS bundle delta documented in PR description

## Out of scope (do not build)

- Backend endpoints — already wired, returning `[]` until SQL lands
- Authentication — handled by parent shell
- Tenant switching — handled by parent shell
- Predictive bid scoring — v3, separate module
- Choropleth map — v2.1
- Export to CSV — v2.1
- Storybook — not in codebase; use Vitest

## Deliverable

Open a PR against `feature/market-intel-v15` with:

1. The full module per the structure above.
2. `frontend/src/modules/market-intel/README.md` documenting the API
   contract, mock-data toggle, and how to add a new tab.
3. Vitest tests for `CompetitorCurves`, `OpportunityGaps`,
   `BidCalibration` — each with empty/loading/error/populated states.

Hand back to Lead for review + merge into `feature/market-intel-v15`
(NOT main — main merge is gated on v1 deploy lock per agent_board).
