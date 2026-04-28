# PROPOSED_CHANGES — `/productivity` route + sidebar nav

**From**: Vendors Module Worker (Agent #1)  
**To**: Lead Agent (+ Frontend Polish for `nav-config.tsx`)  
**Date**: 2026-04-28  
**Touches Lead-owned**: `frontend/src/routes.tsx`  
**Touches Frontend Polish-owned**: `frontend/src/components/shell/nav-config.tsx`

## Why

Productivity backend (`GET /api/productivity/summary`, `/attention`, `/jobs/{job_id:path}`) is shipped. This folder adds the consumer: KPI strip, Overview + Attention tabs, job detail sheet. Mounting requires route registration; primary operational page should appear under **OPERATIONS** in the sidebar.

## What to add

### 1. Route — `frontend/src/routes.tsx`

Import (place with other Operations modules):

```tsx
import { ProductivityPage } from "@/modules/productivity/ProductivityPage";
```

Route entry (suggested: after `jobs`, before Finance group comment):

```tsx
          { path: "jobs", element: <JobsPage /> },
          { path: "productivity", element: <ProductivityPage /> },

          // Finance
```

### 2. Sidebar nav — `frontend/src/components/shell/nav-config.tsx`

**Intent for Frontend Polish**: Add under **OPERATIONS** (with Equipment, Work Orders, Timecards, Jobs):

- **Label**: `Productivity`
- **Icon**: `TrendingUp` or `BarChart3` from `lucide-react` (whichever matches shell patterns)
- **to**: `/productivity`

Example insertion after Jobs:

```tsx
      { label: "Jobs", icon: Briefcase, to: "/jobs" },
      { label: "Productivity", icon: TrendingUp, to: "/productivity" },
```

(Adjust icon import at top of `nav-config.tsx`.)

## Backwards-compat / risk

- Net-new route and nav item. No path changes to existing routes.
- No backend changes; consumes existing productivity module only.

## Verification after mount

1. `cd fieldbridge/frontend && npm run typecheck && npm run lint`
2. Dev: log in, open `/productivity`.
3. Confirm: KPI tiles and resource mini-cards load; **Attention** tab shows rows (or empty state); clicking a row opens the sheet and loads phase grid without console errors.
