# Agent Board — FieldBridge

Coordination ledger for the Lead Agent and worker streams. Updated by Lead on
every PR review/merge. Workers read this at session start to find their lane
and the open contract surface.

## How this works

- **Lead Agent owns**: `app/main.py`, `app/core/*`, `app/models/*`,
  `app/services/excel_marts/__init__.py` (registry only),
  `frontend/src/routes.tsx`, `frontend/src/layouts/*`,
  `frontend/src/components/RecommendationsRail.tsx`, this file, and PR
  review/merge. **Refinement (2026-04-28)**: integration-point edits
  to `frontend/src/layouts/AppShell.tsx` are permissible from the
  Frontend Polish worker so long as substantive logic stays in
  `frontend/src/components/shell/*`. AppShell.tsx may receive thin
  provider wiring + shell-component imports without a formal Lead
  handoff; any net-new layout component or routing decision still
  goes through Lead.
- **Workers own**: their module folder (`backend/app/modules/<name>/*`,
  `frontend/src/modules/<name>/*`, `app/services/excel_marts/<name>/*`),
  unit tests for it, and a `PROPOSED_CHANGES.md` if they need anything
  outside that boundary.
- **Hard rules**:
  - Workers never edit Lead-owned files. Open a `PROPOSED_CHANGES.md` in
    your module folder and let Lead wire it.
  - Vista SQL stays Vista-specific. No generic ERP-adapter abstraction.
  - Mart writes are Vista-via-REST or CSV import only. Never SQL writes
    against Vista.
  - Shared schema (anything in `app/models/*` or cross-module Pydantic)
    requires PROPOSED_CHANGES.md sign-off from Lead before the worker
    edits it.

## Worker streams

| Stream             | Backend module                     | Frontend module                | Mart                                | Status         |
|--------------------|------------------------------------|--------------------------------|-------------------------------------|----------------|
| Vendors            | `app/modules/vendors`              | `src/modules/vendors`          | `mart_vendors`                      | Live + LLM     |
| Equipment          | `app/modules/equipment`            | `src/modules/equipment`        | `mart_equipment`                    | Live + LLM     |
| Work Orders        | `app/modules/work_orders`          | `src/modules/work-orders`      | `mart_work_orders`                  | Live + LLM     |
| Bids               | `app/modules/bids`                 | `src/modules/bids`             | `mart_bids`                         | Live + LLM     |
| Proposals          | `app/modules/proposals`            | `src/modules/proposals`        | `mart_proposals`                    | Live + LLM     |
| Jobs               | `app/modules/jobs`                 | `src/modules/jobs`             | `mart_jobs`                         | Live + LLM     |
| Timecards          | `app/modules/timecards`            | `src/modules/timecards`        | `mart_timecards`                    | Live + LLM     |
| Cost Coding        | `app/modules/cost_coding`          | `src/modules/cost-coding`      | `mart_cost_coding`                  | Live + LLM     |
| Frontend Polish    | (none)                             | `routes.tsx`, `layouts/`       | —                                   | Lead-owned     |
| Tests/CI           | `backend/tests/`, `.github/`       | (vitest later)                 | —                                   | Healthy        |
| Market Intel BE    | `app/services/market_intel/`, `app/modules/market_intel/{service,router}` SQL fill-in | (none) | `bid_events`, `bid_results`, `contractors` (NEW, not mart_*) | **v1.5 — branch only, see below** |
| Market Intel FE    | (none)                             | `src/modules/market-intel`     | —                                   | **v1.5 — branch only, see below** |

### Adjacent modules already shipped (not in the 10 but tracked)

| Module                  | Backend                                    | Frontend                          | Status        |
|-------------------------|--------------------------------------------|-----------------------------------|---------------|
| Fleet P&L               | `app/modules/fleet_pnl`                    | `src/modules/fleet-pnl`           | Live          |
| Productivity            | `app/modules/productivity`                 | (TBD)                             | Backend live  |
| Executive Dashboard     | `app/modules/executive_dashboard`          | `src/modules/executive-dashboard` | Live          |
| Activity Feed           | `app/modules/activity_feed`                | `src/modules/activity-feed`       | Live          |
| Predictive Maintenance  | `app/modules/predictive_maintenance`       | `src/modules/predictive-maintenance` | Live (LLM stub) |

### Equipment

- 2026-04-27 — Equipment Worker accepted Status Board contract:
  add `GET /api/equipment/status` over `mart_equipment_utilization`,
  `mart_work_orders`, `mart_equipment_transfers`, and `mart_asset_barcodes`;
  wire mobile-first Status tab inside `src/modules/equipment`; propose any
  dedicated `/equipment/status` route through module `PROPOSED_CHANGES.md`.
- 2026-04-28 — Status Board shipped + Lead-merged. Worker delivered the
  `/api/equipment/status` endpoint, the Status tab inside EquipmentPage,
  and two PROPOSED_CHANGES.md (one for indexes, one for the route).
  Lead (a) merged the worker bundle, (b) wired `/equipment/status` in
  routes.tsx, (c) accepted 4 of 5 proposed mart indexes (rejected
  `mart_asset_barcodes (tenant_id, barcode)` — structurally identical
  to existing PK). Worker should re-run their 500-asset benchmark to
  confirm Status Board drops below the 200ms target.

## Pending Lead Agent Reviews

- **Predictive Maintenance LLM prompt** — Backend module shipped with a
  stubbed Phase-6 system prompt. With the canonical six (work_orders,
  jobs, timecards, cost_coding, bids, proposals) now landed, this is
  next in line for the LLM Prompts Worker. fleet_pnl is the remaining
  stub after PM.
- **Vendors enrichment integration test (deferred)** — Vendors worker
  shipped `tests/integration/test_vendors_enrichment.py` end-to-end
  test against the new endpoint + LEFT JOIN read path. The test imports
  `tests/integration/{conftest,harness}.py` from the Tests/CI bundle
  which hasn't been Lead-merged yet. The test also has a duplicate
  hand-written `CREATE TABLE mart_vendor_enrichments` that needs the
  same surgical removal as the unit test in 8a0129f. Both will be
  resolved when Tests/CI's bundle lands.
- **Tests/CI workflow registration** — `fieldbridge/.github/workflows/ci.yml`
  has been expanded into 4 jobs by Agent #5 but lives at a subdirectory
  path GitHub Actions does not register. `gh workflow list` does not show
  it; no commit on this repo has ever triggered pytest in CI. See
  `backend/tests/PROPOSED_CHANGES.md` (commit `db9b6df`). Needs Tests/CI
  Worker to relocate to `.github/workflows/ci.yml` at repo root or add
  a thin root forwarder. **Until then**, "Healthy" status on the Tests/CI
  row is local-only — the suite is genuinely green on dev WSL but is
  not enforced at push time.

## LLM Prompts

- **2026-04-27 — Agent #3**: Started Phase-6 LLM prompt worker lane. Reading
  equipment/vendors canonical prompts first, then filling modules in order:
  work_orders, jobs, timecards, cost_coding, bids, proposals.
- **2026-04-28 — Agent #3 (all 6 shipped, Lead-merged)**: Filled in
  `prompts.py` + new `insights.py` + `GET /recommendations` router edits
  + 12 unit tests across all six target modules. Lead audited (PASS 6/6
  via Explore lane-discipline pass), ran the new test set (76 passed,
  1 skipped — the skip is fleet_pnl which is intentionally still a stub),
  and merged as six per-module commits in fill-in order. Phase-6 LLM
  rail is now live on 8 of 9 backend modules; only `fleet_pnl` and
  `predictive_maintenance` remain stubbed, in that priority order.

## Tests/CI

- **2026-04-27 — Agent #5**: Started Tests & CI worker lane. Read
  `tests/conftest.py`, `tests/unit/test_proposals_module.py` (canonical
  pattern), and the existing `.github/workflows/ci.yml`. **Posted current
  per-module coverage** below + **proposed coverage-gate ramp**. Net-new
  artifacts (all in Tests/CI lane — no production source touched):
  - `backend/pyproject.toml` — pytest + coverage + ruff config; sets
    `pythonpath="."` so `pytest tests/` works from `backend/` without an
    explicit `PYTHONPATH`.
  - `backend/tests/integration/{__init__,conftest,harness}.py` —
    factory `build_integrated_engine(tmp_path)` spins up a SQLite engine
    with **every** mart Table from `app.services.excel_marts` registered
    + a known tenant seeded. Re-usable across modules; new marts get
    picked up automatically via `Base.metadata`.
  - `backend/tests/integration/test_harness_smoke.py` — guards the
    harness contract (engine bootstrap, table registration, round-trip).
  - `backend/tests/llm/test_prompt_smoke.py` — parses every
    `app/modules/*/prompts.py` and asserts each `SYSTEM_PROMPT` either
    self-identifies as a `[STUB]` or contains all five canonical
    sections (role / quality bar / context shape / style / tool ref).
    Catches regression when LLM Prompts Worker fills in a stub but
    forgets a section.
  - `backend/tests/safety/test_no_fstring_sql.py` — AST lint pass over
    `app/modules/*/service.py`. Flags any f-string SQL whose values
    don't resolve to module-level literals, with an explicit
    `KNOWN_SAFE_FSTRING_SQL` waiver list (4 entries today, each with
    a justification + a self-test that fails when the waiver goes
    stale). All current production f-string usages are structural-only
    (column lists, internal-caller table names) — no user-input path
    into SQL.
  - `.github/workflows/ci.yml` — expanded into 4 jobs:
    `backend-lint` (ruff check + scoped format-check) →
    `backend-test` (pytest + coverage gate `${COV_FAIL_UNDER:-65}`) →
    `frontend-lint` (eslint + tsc) →
    `frontend-test` (vitest if the script exists; advisory otherwise
    until the frontend test runner is wired up). Concurrency-cancels
    superseded runs.

  ### Current backend coverage (2026-04-27, full suite)

  | Scope                       | Lines | Cov%  |
  |-----------------------------|------:|------:|
  | **Overall**                 | 8,331 | 68.6% |
  | `app/modules`               | 5,573 | 79.7% |
  | `app/services`              |   814 | 99.3% |
  | `app/models`                |   177 | 94.9% |
  | `app/core`                  |   518 | 57.3% |
  | `app/api`                   | 1,206 |  0.0% |

  Per-module:

  | Module                  | Lines | Cov%   | Status |
  |-------------------------|------:|-------:|--------|
  | activity_feed           |   260 | 93.1%  |        |
  | bids                    |   551 | 82.0%  |        |
  | cost_coding             |   482 | 80.7%  |        |
  | equipment               |   496 | 57.1%  | weak   |
  | executive_dashboard     |   277 | 92.4%  |        |
  | fleet_pnl               |   552 | 94.0%  |        |
  | jobs                    |   474 | 78.9%  |        |
  | predictive_maintenance  |   528 | 93.8%  |        |
  | productivity            |   313 | 93.0%  |        |
  | proposals               |   383 | 76.5%  |        |
  | timecards               |   362 | 73.5%  |        |
  | vendors                 |   524 | 60.3%  | weak   |
  | work_orders             |   371 | 72.2%  |        |

  ### Proposed coverage-gate ramp

  | Quarter   | `COV_FAIL_UNDER` | Rationale                                       |
  |-----------|-----------------:|-------------------------------------------------|
  | 2026-Q2   |              65% | We're at 68.6% — start under the floor so day-1 CI doesn't red-light unrelated PRs. |
  | 2026-Q3   |              70% | Equipment + Vendors get a coverage push; `app/core` paths covered by integration harness adoption. |
  | 2026-Q4   |              75% | `app/api` test sweep — any endpoint touched in a PR ships with a TestClient test. |
  | 2027-Q1   |              80% | Steady state per CLAUDE.md target.              |

  CI reads the threshold from `${COV_FAIL_UNDER}` so quarterly bumps
  are a one-line workflow edit — no tooling change needed.

  ### Known per-file ignores (clear when fixed)

  Tracked in `backend/pyproject.toml` `[tool.ruff.lint.per-file-ignores]`:
  - `app/api/v1/endpoints/bids.py` — E401 (`import os, tempfile`)
  - `app/api/v1/endpoints/media.py` — E401 (`import os, tempfile`)
  - `app/modules/vendors/service.py` — F402 (loop var `field` shadows
    `dataclasses.field` import)

## Frontend Polish

- **2026-04-27 — Agent #4 (initial)**: Started Frontend Polish worker lane.
  Read `layouts/AppShell.tsx`, `components/shell/{Sidebar,Topbar,nav-config}.tsx`,
  `components/RecommendationsRail.tsx`, and three module pages
  (Equipment / Jobs / Work Orders) end-to-end. Posted mobile-shell
  breakpoint plan to Lead for review before any code lands. Initial scope:
  (1) responsive AppShell with Sheet-based sidebar below `md`,
  (2) `field-mode` class on AppShell root for high-contrast + 44px touch
  targets, (3) RecommendationsRail a11y pass (ARIA on severity badges,
  keyboard nav, `prefers-reduced-motion`), (4) `<StyleGuide>` component at
  `components/style-guide/` for Lead to mount at `/style-guide`. Net-new
  shadcn primitive: `components/ui/sheet.tsx` (lane-internal, no module
  impact). RecommendationsRail public props stay backward-compatible —
  EquipmentPage's existing `<SharedRecommendationsRail moduleSlug=…>` call
  site won't change.

- **2026-04-27 — Agent #4 (rocks 1–3 landed)**: Lead green-lit the plan.
  Shipped:
  1. `components/ui/sheet.tsx` — new shadcn Sheet primitive (Radix Dialog).
     Added `@radix-ui/react-dialog@^1.1.2` to `package.json`.
  2. Responsive AppShell. New files:
     `components/shell/app-shell-context.ts` (context + hook),
     `components/shell/AppShellProvider.tsx`,
     `components/shell/MobileSidebar.tsx`. Refactored:
     `components/shell/Sidebar.tsx` (extracted `SidebarBody` for reuse),
     `components/shell/Topbar.tsx` (hamburger + field-mode toggle),
     `layouts/AppShell.tsx` (responsive grid, `data-field` root attr,
     breakpoint contract documented in header). Desktop behavior at md+
     is byte-for-byte preserved.
  3. `styles/field-mode.css` — high-contrast token re-points + 44×44 tap
     targets, scoped to `[data-field="true"]`, imported from `index.css`
     above `@tailwind` directives.
  4. `RecommendationsRail.tsx` a11y pass — `role="region"` +
     `aria-labelledby` + `aria-busy`, sr-only `aria-live="polite"`
     status, roving-tabindex over cards (Arrow/Home/End), severity badge
     `aria-label`, `motion-reduce:animate-none` on spinner + skeleton.
     **Public props unchanged** — Equipment/Vendors call sites untouched.

  **Lane-expansion note for Lead**: my brief explicitly tasked me with
  "Mobile-responsive AppShell" but the board originally listed `layouts/`
  as Lead-owned. I edited `layouts/AppShell.tsx` to honor the brief; if
  you'd rather have layouts/ stay strictly Lead-territory, reassign and
  I'll move the responsive logic into `components/shell/AppShellRoot.tsx`
  with AppShell.tsx as a thin wrapper.

  Verification: `npm run typecheck` ✅, `npm run build` ✅ (35.22 kB CSS,
  +1.16 kB from field-mode rules). `npm run lint` shows 3 pre-existing
  warnings (badge.tsx, button.tsx, main.tsx — react-refresh) unchanged
  by this work; my new files contribute zero warnings.

  Not yet done: (4) `<StyleGuide>` component for `/style-guide`. Next
  rock.

- **2026-04-28 — Agent #4 (rock 4 landed)**: Built `<StyleGuide>` at
  `frontend/src/components/style-guide/StyleGuide.tsx`. Single-file demo
  page with 11 sections: tokens (surfaces + semantic), severity tones
  (the canonical 5-tone system), typography scale, button variants ×
  sizes, badges, cards (standard + KPI accent), inputs (Input + Switch),
  Tabs (Overview / List / Insights pattern), Sheet (interactive demo
  for all 4 sides), Recommendations rail visual preview (static — no
  fetch), and a scoped field-mode preview with in-page toggle for A/B
  contrast comparison. No new tokens, only existing semantic variables.

  **Lead handoff**: route registration is in `frontend/src/routes.tsx`
  (Lead-owned). Drop-in instructions live in
  `frontend/src/components/style-guide/PROPOSED_CHANGES.md`. Suggested
  placement: after Knowledge group, before catch-all, with no sidebar
  nav entry (internal-team-facing, dev-only URL).

  Verification: `npm run typecheck` ✅, `npm run build` ✅
  (35.78 kB CSS, +0.56 kB from StyleGuide-only utilities). Zero new
  lint warnings; same 3 pre-existing react-refresh warnings as before.

  All four CURRENT WORK PRIORITIES from the brief are now landed.
  Awaiting Lead route registration for `/style-guide`, then a manual
  smoke-test pass on mobile viewport sizes.

- **2026-04-28 — Agent #4 (lint cleanup + test infra)**: Took the two
  optional follow-ups while waiting on Lead.

  **(a) `npm run lint` is now green for the first time.** The three
  pre-existing react-refresh warnings are gone:
  - `components/ui/badge.tsx` — dropped the unused `badgeVariants`
    named export (no consumers across the codebase).
  - `components/ui/button.tsx` — dropped the unused `buttonVariants`
    named export (same).
  - `main.tsx` — extracted the inline `<Root>` component to a sibling
    `frontend/src/Root.tsx` so the entry file no longer mixes a component
    declaration with side-effect-only render code.

  Both `cva` variant functions stay defined locally in their files
  (still used inside `VariantProps<typeof ...>` and `cn(...)` calls).
  If a future consumer needs them re-exposed, the canonical fix is to
  pull them into a sibling `*-variants.ts` file — leaving that for
  whoever needs it.

  **Lane note**: `main.tsx` is not explicitly in any worker's owned
  paths; it's an entry-point file. Created `Root.tsx` next to it. Flag
  for Lead if this should belong elsewhere.

  **(b) Vitest test infra is wired** under
  `frontend/src/components/__tests__/`. Added devDeps:
  `vitest`, `@vitest/coverage-v8`, `@testing-library/react`,
  `@testing-library/jest-dom`, `@testing-library/user-event`,
  `happy-dom`. (Tried jsdom@27 first — it requires Node ≥20.19 and we
  ship on 20.18, so swapped to happy-dom which is the lighter modern
  default for Vitest.)

  Setup file at `frontend/src/test/setup.ts` shims `matchMedia`,
  `ResizeObserver`, and the pointer-capture/scrollIntoView Element
  prototype methods that Radix Dialog reaches for at mount.
  `vite.config.ts` gained a `test:` block (happy-dom env, globals on,
  setup file path).

  Two test files committed, both green:

  - `__tests__/AppShell.test.tsx` — locks in the breakpoint contract
    (root has `flex flex-col md:grid md:grid-cols-[240px_1fr]`,
    desktop sidebar has `hidden md:flex`, hamburger has `md:hidden`),
    the mobile drawer wiring (hamburger → role="dialog" with
    aria-labelledby/described-by + sr-only Navigation title), and the
    field-mode toggle (data-field absent default, `"true"` on press,
    removed on second press, aria-pressed flips).

  - `__tests__/RecommendationsRail.test.tsx` — locks in the a11y
    contract (region with aria-labelledby, aria-busy mirroring fetch
    state, sr-only aria-live="polite" status text, severity badges
    with `aria-label="Severity: {level}"`, affected-assets list
    labelled), the roving-tabindex behavior (initial article has
    tabindex 0, ArrowDown/End/Home shift focus + flip tabindex,
    ArrowUp at index 0 stays put — no wrap), and the reduced-motion
    utility on skeletons.

  New scripts: `npm test` (vitest run) and `npm run test:watch`
  (vitest watch). Run results: **17/17 passing** in 5.07s.

  Verification across the full pipeline:
  - `npm run typecheck` ✅
  - `npm run lint` ✅ (0 warnings — first time green)
  - `npm test` ✅ (17/17)
  - `npm run build` ✅ (35.78 kB CSS, prod bundle unaffected)

  Backend CI still runs `pytest -v` only, so this doesn't touch the
  CI green/red status — but `npm test` is now wireable into CI when
  Lead is ready.

- **2026-04-28 — Agent #4 (CI proposal + mobile smoke pass)**: Two
  follow-ups from Lead's reply on `npm test`-in-CI.

  **(a) `frontend/PROPOSED_CHANGES.md` for Tests/CI Worker (Agent #5).**
  Per Lead's lane discipline note (`.github/workflows/` is Tests/CI
  territory, not mine), I did NOT edit `ci.yml` directly. Instead
  dropped a turnkey job snippet at `frontend/PROPOSED_CHANGES.md`.
  Verified locally that the snippet runs cleanly:

  ```
  npm test -- --coverage --reporter=default --reporter=junit \
    --outputFile.junit=vitest-junit.xml
  → 17/17 passed in ~8s
  → JUNIT report written to vitest-junit.xml
  → Coverage HTML at coverage/index.html (Statements 67.97% across
    files actually loaded by tests)
  ```

  Snippet matches `backend-test`'s conventions: `needs: frontend-lint`,
  `actions/setup-node@v4`, `cache: npm`, parallel coverage HTML +
  junit artifact uploads via `actions/upload-artifact@v4` with
  `if: always()`. No threshold gate at first activation — phasing
  proposal included so Tests/CI can ratchet up as module workers
  add tests, mirroring backend's quarterly `COV_FAIL_UNDER` bump.

  Heads-up to Tests/CI: **happy-dom (not jsdom)** for env reasons
  (Node 20.18 vs jsdom@27's 20.19 minimum). Means no system-level
  Chromium needed in CI; `ubuntu-latest` runs it bare. No env vars
  required (auth state stubbed via `useAuth.setState`,
  `fetchRecommendations` mocked via `vi.mock`).

  Also flagged the gating issue from `backend/tests/PROPOSED_CHANGES.md`
  (commit `db9b6df`): the workflow at
  `fieldbridge/.github/workflows/ci.yml` isn't registered with GitHub
  Actions — workflows must live at repo-root `.github/workflows/`.
  The activation snippet I'm proposing fires only after that
  relocation.

  Also added `*-junit.xml` to `frontend/.gitignore` so the local
  artifact doesn't accidentally land in a commit (`coverage/` was
  already ignored).

  **(b) Mobile-viewport smoke pass on `/style-guide` (commit `bb71e13`).**
  Drove the cursor-ide-browser MCP through `localhost:5173` after
  `devLogin()`. Findings:

  ✅ **Mobile (~375 / ≤600 px) layout works as designed.**
  - Hamburger button renders (`Open navigation` aria-label, 44×44 hit
    target).
  - Desktop sidebar correctly hidden (`hidden md:flex`).
  - Topbar collapses gracefully — Auto Refresh label hides at sm,
    user chip becomes initials-only ("S"), Search hides at md.
  - Color tokens grid stacks to 2 cols, severity tile grid stacks
    cleanly. No overflow, no horizontal scroll.

  ✅ **Mobile sidebar drawer.**
  - Hamburger click opens the Sheet panel from the left, full module
    nav (17 routes, all groups: Main / Operations / Finance /
    Intelligence / Knowledge), `All systems operational` footer.
  - Overlay darkens content behind, focus traps inside the drawer.
  - Esc closes.
  - Sr-only `Navigation` heading + `FieldBridge module navigation`
    description show up correctly in the snapshot tree (Radix
    `aria-labelledby` / `aria-describedby` wiring is honored).

  ✅ **Field-mode toggle (Topbar contrast button).**
  - Click flips `aria-pressed` from false → true and back.
  - `data-field="true"` attribute set on AppShell root verified via
    DOM. Token re-points are visible (semantic surfaces saturate
    slightly, contrast button shows the emerald-tint pressed state).
  - Works at both mobile and the larger viewports the MCP allowed.

  ✅ **Sheet primitive (style-guide demo).**
  - "Open right" verified — overlay, sheet pane, focus moves to
    auto-focused Close button (focus trap engaged), Esc closes.
  - All four trigger buttons (`Open top` / `right` / `bottom` /
    `left`) render with `[collapsed]` initial state and flip to
    `[expanded]` on click.

  ⚠️ **Density issue at md ≤ width < lg (≈768-1023 px) in the Topbar.**
  Spotted in the first cycle before the MCP browser dropped to mobile.
  At ~850 px (sidebar 240 px + main column ≈610 px), the Topbar's
  right-side cluster competes for space:

  - `TenantSwitcher` button uses `text-lg` (18 px) for the tenant
    name + `flex items-center gap-1` for name+chevron — no
    `truncate` or `max-w` cap. Long tenant names will wrap in the
    flex column.
  - `Search` is a hard `w-[300px]` starting at md. That's ~50% of
    available right-column width on its own at 768 px.
  - `Auto Refresh` text label shows from sm+ (≥640) — visible alongside
    a hard-width 300 px search at md.

  Visible failure: "VanCon Inc." wraps to two lines (`VanCon` /
  `Inc.`) and "Auto Refresh" wraps (`Auto` / `Refresh`) at that
  breakpoint band.

  Surgical fix (all three in my lane, `components/shell/`):

  ```
  // TenantSwitcher.tsx — name span:
  className="flex items-center gap-1 text-lg font-semibold tracking-tight
             max-w-[160px] truncate md:max-w-none"

  // Topbar.tsx — Search:
  className="w-[180px] pl-9 lg:w-[300px]"
  // OR (more aggressive):
  className="hidden pl-9 lg:block w-[300px]"

  // Topbar.tsx — Auto Refresh label span:
  className="hidden text-sm font-medium text-foreground lg:inline"
  ```

  Awaiting Lead direction on whether to land this as a follow-up
  patch or hand off to Home / a future polish pass. It's <30 lines.

  ✅ **Performance card (commit `2488451`).** The collision Lead
  patched only matters at lg+ (the metric strip and chart sit
  side-by-side). Below lg the layout stacks vertically, eliminating
  the collision before it could happen — the mobile rendering of
  the home dashboard's Performance card looks clean (header pills
  fit on one row, metric strip + chart stack with proper spacing).

  ⚠️ **MCP browser limitation.** After the first navigate the
  cursor-ide-browser tab settled at a ~600 px effective viewport
  and stopped honoring `browser_resize` upward. Couldn't reliably
  exercise 768 / 1024 / 1280 / 1440 visuals through the MCP.
  Recommendation: Lead does the manual desktop-viewport pass in a
  real browser. The AppShell test file
  (`__tests__/AppShell.test.tsx`) locks in the responsive class
  contract at the DOM level so a regression can't ship silently
  even without that visual pass running on every PR.

  All of the above ran with no console errors, no failed network
  calls (style-guide page is static), no React warnings.

- **2026-04-28 — Agent #4 (density patch landed, Phase 1 brief
  closed)**: Density patch landed at `6e342db` per Lead's exact
  prescription with one breakpoint correction:

  - `TenantSwitcher`: name span now
    `max-w-[160px] truncate lg:max-w-none` (NOT `md:` —
    Lead caught the breakpoint range mistake; the cap needs to
    stay through the md..lg gap and only release at lg, where the
    sidebar's back and the topbar has the room).
  - `Topbar` Search: `w-[180px] pl-9 lg:w-[300px]` — keeps tablet-
    portrait users able to type real queries; no feature drop.
  - `Topbar` Auto Refresh label: `hidden text-sm font-medium
    text-foreground lg:inline` — was `sm:inline`. Switch already
    carries `aria-label="Auto refresh"` (verified pre-commit) so
    SR users read the label even with the visual span hidden.
  - Bonus: added `shrink-0` on the TenantSwitcher chevron — without
    it the icon can compress alongside the truncated text in a flex
    container. Standard truncate+icon pattern; Lead diff didn't
    explicitly call it but it's required for the truncate to do
    what it advertises.

  Verified pre-commit: typecheck / lint / vitest (17/17) / build all
  green; CSS bundle delta +0.17 kB raw / +0.05 kB gzip from the four
  extra Tailwind utilities. Two files changed (`TenantSwitcher.tsx`,
  `Topbar.tsx`), 4 insertions, 4 deletions.

  **Phase 1 brief is now closed.** Working-tree state still has
  uncommitted lint cleanup + Vitest infra + CI proposal from earlier
  in the session — those are separate from the density patch and
  await Lead's call on whether to bundle/squash or land as their
  own commit(s).

  **Next-brief proposal (NOT auto-starting per Lead's directive):**

  | Rank | Brief                                       | User-pain                                                      |
  |------|---------------------------------------------|----------------------------------------------------------------|
  | 1    | (c) Frontend perf — bundle + lazy routes    | 1.57 MB JS / 408 kB gzip on first load. 17 routes shipped in   |
  |      |                                             | one chunk. Field workers on 4G eat 5-10s of waiting before     |
  |      |                                             | the app boots — the same audience field-mode is for.           |
  | 2    | (a) Phase 2 a11y spec + reference module    | Pattern established on RecommendationsRail. Best as            |
  |      |                                             | spec-first: write `docs/a11y-contract.md`, apply to one        |
  |      |                                             | reference module (Equipment), module workers adopt their own.  |
  |      |                                             | Avoids cross-lane churn.                                       |
  | 3    | (b) Skeleton / loading-state primitive      | Partial coverage exists (rail, dashboards). Net win is visual  |
  |      |                                             | consistency more than load-time. Important but not urgent.     |

  Pitch: open the perf brief on (c). Concrete wins visible from the
  current build:
  - Route-level `React.lazy()` + `Suspense` for the 17 module pages
    (most users hit 1-2 per session).
  - Code-split Recharts (heavy, used only on dashboards).
  - Audit the @tanstack/react-table import surface (used in a few
    places, likely full-package import).
  - `vite.config.ts` `manualChunks` for vendor splitting.

  Estimated initial-bundle reduction: 50%+ → ~700 kB raw / ~200 kB
  gzip. CI build time will increase ~5-10s from the chunk-graph
  resolution but that's nothing against the runtime UX win. Awaiting
  Lead's pick.

## Market Intel (v1.5 — branch-only)

- **2026-04-29 — Lead** scaffolded `feature/market-intel-v15` off
  `main`. **Do NOT merge to main until v1 deploy is locked.** The
  branch holds the schema + module skeleton + worker briefs; auto-deploy
  on Render only fires from main, so this branch is safe to develop in
  parallel for weeks.

  Strategic context: state-by-state public bid network scraping
  (NAPC's `{state}bids.{com,net}` portals + state DOT bid tabs) →
  unified dataset → Bid Intelligence layer. Full design in
  `docs/market-intel.md`. The "Bid Intelligence" UI is a peer route
  at `/market-intel`, sidebar entry under Intelligence between
  Bids and Proposals. Future regrouping under `/intelligence/*`
  parent in v3 documented as a known future move.

  Scaffold landed:
  * `app/models/{bid_event,bid_result,contractor}.py` — three new
    tenant-scoped tables. `tenant_id` on every row; shared-network
    sentinel for cross-tenant data.
  * `app/models/tenant.py` extended with `kind` enum column
    (`customer | shared_dataset | internal_test`). Defaulted to
    `customer` so existing rows are unaffected.
  * `app/core/seed.py` extended: deterministic UUIDv5 sentinel
    `7744601c-1f54-5ea4-988e-63c5e2740ee3` from
    `uuid5(NAMESPACE_DNS, "shared.fieldbridge.network")`. New
    `_seed_shared_network_tenant` step is idempotent.
  * `backend/scripts/migrate_tenants_add_kind.py` — one-shot
    `ALTER TABLE tenants ADD COLUMN IF NOT EXISTS kind ...` for
    prod environments seeded before this column existed. Run from
    Render Shell when this branch eventually merges.
  * `app/modules/market_intel/{router,schema,service}.py` — read API
    mounted at `/api/market-intel/{competitor-curves,opportunity-gaps,bid-calibration}`.
    Routes return 200 with `[]` (NOT 501) until the Backend Worker
    fills in SQL — matches production state during dark accumulation.
  * `app/services/market_intel/` — service folder with README +
    worker brief. Scrapers, normalizers, analytics SQL templates,
    pipeline orchestrator: all to be filled in by Market Intel
    Backend Worker.
  * `frontend/src/modules/market-intel/MarketIntelPage.tsx` —
    placeholder shell so the route resolves. Full UI brief in
    `frontend/src/modules/market-intel/PROPOSED_CHANGES.md`.
  * `frontend/src/routes.tsx` + `components/shell/nav-config.tsx`
    wired.
  * `docs/market-intel.md` — full design doc, locks navigation
    contract + tenant scoping pattern + risk flags (NAPC ToS,
    robots.txt, PII).

  **Worker stream spinup (2 streams)**:
  * **Market Intel Backend Worker** — first task: `registry.py`
    probe across 50 NAPC state portals → commit
    `state_portal_registry.json`. Then 50 captured Idaho post
    fixtures + `parse_bid_post` validation. Brief at
    `app/services/market_intel/README.md`.
  * **Market Intel Frontend Worker** — first task: full UI per
    brief at `frontend/src/modules/market-intel/PROPOSED_CHANGES.md`.
    Runs against `VITE_USE_MOCK_DATA=true` until backend SQL lands.

  Lane discipline: branch-isolated. Workers' PRs target
  `feature/market-intel-v15` for review, NOT main. Lead reviews +
  merges into the feature branch. Final feature-branch → main merge
  is a single Lead operation gated on v1 lock.

- **2026-04-29 — Backend Worker first slices landed**:
  * PR #6 (`90e2046`): NAPC state portal registry probe — 50/50
    states resolved, ProbeStatus 11-value enum, parking detection,
    www-fallback, MA `mass` stem override, run_napc_probe.py
    operator tool, 54 shape-assertion tests.
  * PR #8 (`561ba6b`): registry follow-ups — `schema_version: "1"`
    on JSON via `write_registry()`, drift-proof test asserts
    (`agent == registry_module.USER_AGENT`,
    `schema_version == REGISTRY_SCHEMA_VERSION`),
    `beautifulsoup4>=4.12.0` and `lxml>=5.2.0` in requirements.txt.

- **2026-04-29 — Frontend Worker first slices landed**:
  * PR #5 (`0f637e1`): slice 1 — module skeleton, hooks, KPI strip.
    15 files, 17 vitest tests, four lazy chunks split. CSS +1.83 kB
    raw / +7.82 kB gzip.
  * PR #7 (`0037c85`): slice 2 — Competitor curves tab.
    Recharts ScatterChart + sortable Table + side Sheet drilldown.
    Cross-lane semantic tokens (`--color-good` teal, `--color-watch`
    coral) added to `index.css` + `tailwind.config.ts` per Lead's
    PR-#5 ask. Win-rate ramp keeps hue/saturation locked, varies
    only lightness. 6 new vitest tests = 23/23 total.

- **2026-04-29 — STRATEGIC PIVOT: NAPC paused, State DOT primary**.
  Backend Worker hit `idahobids.com/robots.txt`'s explicit
  `User-agent: * Disallow: /` with a named-allowlist of ~21 search
  engines. FieldBridge's UA isn't on the list. Bypassing would
  violate the design doc's load-bearing robots commitment. Lead +
  Operator decision:

  * **A. Pivot v1.5 primary source to State DOT bid tabulations
    (ITD first, UDOT/NDOT in v1.5b).** Government-published-as-
    public-record. Heavy-civil precision target. PDF parsing via
    pdfplumber. Schema/API/frontend unchanged.
  * **B. One-time fixture-capture override for NAPC.** REJECTED.
    "We want fixtures" isn't a real reason. Sets a bad precedent.
  * **C. NAPC partnership outreach.** PURSUED IN PARALLEL.
    Lead/Operator-driven, not a worker dependency. If outreach
    succeeds the moat compounds; if it doesn't, no one's blocked.

  Full rationale + the rejected-options analysis live in
  `docs/market-intel.md` -> "Data source pivot" + "Risk flags"
  (revised). Backend Worker's next PR pivots slice 2 to ITD and
  drops `_napc_paused.md` documenting the pause at the
  `napc_network/scrapers/` boundary. Registry + JSON stay
  committed — they're an intelligence asset for the partnership
  outreach.

- **2026-04-29 — Frontend Worker (Agent #2) stood down — brief
  closed end-to-end**. Four slices, four PRs, zero cross-lane edits.

  | Slice | PR  | Commit    | Scope                                              |
  |-------|-----|-----------|----------------------------------------------------|
  | 1     | #5  | `0f637e1` | Module skeleton, hooks, KPI strip, four lazy chunks |
  | 2     | #7  | `0037c85` | Competitor curves tab — Scatter + Sheet + Table; teal/coral semantic tokens added cross-lane per Lead ask |
  | 3     | #9  | `257bc67` | Opportunity gaps tab — BarChart + top-10 + scope filter; first coral use, ramp HSL channel-locked |
  | 4     | #10 | `d899237` | Bid calibration tab (brief-closer) — dual-axis ComposedChart + highlighted-row table; ContractorDetail + GapDetail placeholder pages shipped |
  | wire  | -   | `b1830c0` | Lead-direct: routes.tsx wired for /market-intel/{contractor,gap} detail pages |

  Final test count: 38/38 vitest passing. Cumulative CSS delta:
  +3.09 kB raw (35.78 kB → 38.87 kB) for the entire Market Intel
  static UI. Total deferred Recharts cost across three tabs:
  ~58 kB raw / ~20 kB gzip — all in lazy chunks, none in the
  main bundle.

  **Lane-discipline highlights**: two harness branch-switch
  incidents detected and recovered non-destructively via the
  two-second pre-stage gate (`git rev-parse --abbrev-ref HEAD`
  + `git status --short`). PROPOSED_CHANGES_routes.md is the
  canonical worker→Lead route-handoff template — slugify
  function verbatim, URL encoding rules, edge cases (null county),
  copy-pasteable wiring snippet. Holding it up as the pattern
  for any future Lead-owned-file ask from any worker.

  **Open Frontend follow-ups (queued, NOT urgent)**:
  - Real-a11y audit pass (axe-core + SR walkthrough) — Frontend
    Worker, triggered before v2 lands after pipeline accumulates
  - v2.1 export-to-CSV — parked, post-v2
  - Field-mode contrast for `--color-good` / `--color-watch` —
    routed to Frontend Polish Worker (their lane: `field-mode.css`)

## Recent Merges

| Date       | Module                | Commit    | Notes                                   |
|------------|-----------------------|-----------|-----------------------------------------|
| 2026-04-28 | Vendors (enrichment)  | `8a0129f` | POST /api/vendors/enrichments + LEFT JOIN read path + test fix |
| 2026-04-28 | Vendors (schema)      | `750eb18` | enriched/enriched_at/VendorEnrichmentRequest scaffolding |
| 2026-04-28 | Vendor Enrichments (mart) | `9f4c4f0` | mart_vendor_enrichments overlay table + registry |
| 2026-04-28 | Routes                | `bb71e13` | Wire /style-guide for design system reference |
| 2026-04-28 | Frontend Polish       | `5c7491e` | Responsive AppShell + a11y + StyleGuide bundle (rocks 1-4) |
| 2026-04-28 | Marts (perf)          | `d6f983a` | 4 read-path indexes for Equipment Status Board |
| 2026-04-28 | Routes                | `1b08273` | Wire /equipment/status                  |
| 2026-04-28 | Equipment             | `93a3beb` | Status Board endpoint + page (worker bundle) |
| 2026-04-28 | Proposals (LLM)       | `70fc788` | Phase-6 prompt + insights + /recommendations |
| 2026-04-28 | Bids (LLM)            | `1559337` | Phase-6 prompt + insights + /recommendations |
| 2026-04-28 | Cost Coding (LLM)     | `f3cc670` | Phase-6 prompt + insights + /recommendations |
| 2026-04-28 | Timecards (LLM)       | `3a3f76a` | Phase-6 prompt + insights + /recommendations |
| 2026-04-28 | Jobs (LLM)            | `9ca3729` | Phase-6 prompt + insights + /recommendations |
| 2026-04-28 | Work Orders (LLM)     | `5bfff5e` | Phase-6 prompt + insights + /recommendations |
| 2026-04-27 | Predictive Maintenance | `9b58ddf` | Module + 62 unit tests, mounted at /api/predictive-maintenance |
| 2026-04-27 | Predictive Maintenance (mart) | `5851475` | mart_predictive_maintenance + history table |
| 2026-04-27 | (infra)               | `db9b6df` | PROPOSED_CHANGES.md — CI workflow not registered on GitHub |
| 2026-04-27 | (infra)               | `13cdcb3` | env_file absolute path + extra=ignore — unblocks Phase-6 LLM rail |
| 2026-04-?? | Activity Feed         | `3e3ca35` | Cross-source event stream               |
| 2026-04-?? | (infra)               | `2185258` | Pin bcrypt<4 — passlib startup fix      |
| 2026-04-?? | Executive Dashboard   | `5842637` | Pipeline query Postgres fix             |
| 2026-04-?? | Productivity (mart)   | `db511ab` | Registry wiring                         |
| 2026-04-?? | Productivity          | `9547864` | KPI tiles + attention list              |
| 2026-04-?? | Productivity (mart)   | `49d72f2` | Phase-level hours/units                 |
| 2026-04-?? | (infra)               | `d81e882` | uvicorn startup fix                     |
| 2026-04-?? | Executive Dashboard   | `0403e82` | Cross-module KPI rollup                 |
| 2026-04-?? | Equipment + Vendors   | `628985e` | Phase 6 LLM insights                    |

## Conventions for workers

When you finish a stream-scoped change:

1. Confirm you stayed inside your module folder.
2. If you need a new mart table, add it under
   `app/services/excel_marts/<your_module>/schema.py`. Lead will register
   it in `excel_marts/__init__.py`.
3. If you need a new route, add the router in
   `app/modules/<your_module>/router.py`. Lead will mount it in
   `app/main.py` at `/api/<your-module>`.
4. If you need a new frontend route, add a `PROPOSED_CHANGES.md` in your
   frontend module folder listing the path + component. Lead will wire
   `routes.tsx` and the layout entry.
5. Open a PR. Lead reviews against the rules above and merges.

