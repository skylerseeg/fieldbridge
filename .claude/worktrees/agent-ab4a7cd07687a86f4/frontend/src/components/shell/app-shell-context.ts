import * as React from "react";

/**
 * AppShellContext — session-only state for the authed chrome.
 *
 *  - sidebarOpen: drives the mobile drawer (< md). Topbar's hamburger
 *    flips it; MobileSidebar consumes it. Always false on desktop
 *    because the persistent sidebar doesn't read it.
 *
 *  - fieldMode: high-contrast / 44px-tap-target mode for outdoor field
 *    use. Toggled from the Topbar; AppShell sets `data-field="true"` on
 *    its root, which scopes the overrides in styles/field-mode.css.
 *    Session-only by design — reset on tab close. If a "remember field
 *    mode" preference becomes a product requirement, swap the useState
 *    in AppShellProvider for a useState + localStorage effect.
 *
 * Context + hook live here (no JSX) so the Provider component file can
 * stay component-only and play nicely with React Fast Refresh.
 */
export interface AppShellContextValue {
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  fieldMode: boolean;
  setFieldMode: (on: boolean) => void;
}

export const AppShellContext = React.createContext<AppShellContextValue | null>(
  null,
);

export function useAppShell(): AppShellContextValue {
  const ctx = React.useContext(AppShellContext);
  if (!ctx) {
    throw new Error("useAppShell must be used inside <AppShellProvider>");
  }
  return ctx;
}
