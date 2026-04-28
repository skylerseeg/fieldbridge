# PROPOSED_CHANGES — `/style-guide` route registration

**From**: Frontend Polish Worker (Agent #4)
**To**: Lead Agent
**Date**: 2026-04-28
**Touches Lead-owned**: `frontend/src/routes.tsx`

## Why

CURRENT WORK PRIORITIES item #4 in the Frontend Polish brief calls for a
Storybook-style preview page at `/style-guide` to host the cross-module
design system reference (tokens, severity tones, primitives, the new
Sheet, field-mode preview). The component is built and ready in this
folder; only the route registration is left, and `routes.tsx` is
Lead-owned.

## What to add

### 1. Route entry in `frontend/src/routes.tsx`

Add the import alongside the existing module imports:

```tsx
// Style guide (internal-team-facing design system reference)
import { StyleGuide } from "@/components/style-guide/StyleGuide";
```

Add the route inside the AppShell `children` array. Suggested placement:
**after the Knowledge group, before the catch-all `*` redirect** — keeps
the team-internal page out of the user-facing module list.

```tsx
          // Knowledge
          { path: "project-search", element: <ProjectSearchPage /> },
          { path: "media-library", element: <MediaLibraryPage /> },
          { path: "safety", element: <SafetyPage /> },

          // Internal — design system reference
          { path: "style-guide", element: <StyleGuide /> },

          { path: "*", element: <Navigate to="/dashboard" replace /> },
```

### 2. Sidebar nav entry — recommended NOT to add

`StyleGuide` is for the Frontend Polish lane and module workers, not
for end users. Three options:

1. **No nav entry** (recommended). Devs reach it via direct URL. Keeps
   the user-facing sidebar clean.
2. Add to a new "Internal" group, gated on
   `user.role === "fieldbridge_admin"`.
3. Add it to the existing INTELLIGENCE group unconditionally.

I'd vote (1). If you want (2) or (3), say the word and I'll PR the
`nav-config.tsx` addition since that file is in my lane.

## Backwards-compat / risk

- Net-new route. No existing path changes.
- No backend touch points.
- Component is self-contained; only consumes existing UI primitives + the
  new Sheet primitive (already shipped). Zero coupling to module code.
- No fetches — the rail preview is a static visual mock to avoid spurious
  API hits from a dev tool.

## Verification once mounted

1. `npm run dev`, navigate to `http://localhost:5173/style-guide`.
2. Sections render top-to-bottom: Tokens → Severity → Typography →
   Buttons → Badges → Cards → Inputs → Tabs → Sheet → Recommendations →
   Field mode.
3. Open one Sheet on each side (top/right/bottom/left) — verify focus
   trap and Esc-to-close.
4. Toggle the in-page field-mode switch — observe the scoped contrast
   shift on the wrapper without affecting Topbar / chrome.
5. Resize to 375px — page is responsive (token grid collapses, severity
   tile grid stacks).

Once you wire the route, ping me and I'll do the manual smoke pass.
