import * as React from "react";

import { AppShellContext, type AppShellContextValue } from "./app-shell-context";

/**
 * AppShellProvider — wraps AppShell and supplies the session-only UI
 * state (mobile sidebar open, field mode on/off). Consumers read via
 * `useAppShell()` from ./app-shell-context.
 */
export function AppShellProvider({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = React.useState(false);
  const [fieldMode, setFieldMode] = React.useState(false);

  const value = React.useMemo<AppShellContextValue>(
    () => ({ sidebarOpen, setSidebarOpen, fieldMode, setFieldMode }),
    [sidebarOpen, fieldMode],
  );

  return (
    <AppShellContext.Provider value={value}>
      {children}
    </AppShellContext.Provider>
  );
}
