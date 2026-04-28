import { Outlet } from "react-router-dom";

import { useAppShell } from "@/components/shell/app-shell-context";
import { AppShellProvider } from "@/components/shell/AppShellProvider";
import { MobileSidebar } from "@/components/shell/MobileSidebar";
import { Sidebar } from "@/components/shell/Sidebar";
import { Topbar } from "@/components/shell/Topbar";

/**
 * AppShell — the authed chrome.
 *
 * ─────────────────────────────────────────────────────────────────
 * Breakpoint contract
 * ─────────────────────────────────────────────────────────────────
 *
 *   < md (< 768px)  Mobile / one-handed field use.
 *                    - Sidebar: hidden, lives in a Sheet drawer
 *                      (MobileSidebar). Hamburger trigger in Topbar.
 *                    - Layout: single flex column (Topbar over main).
 *                    - Padding: px-4 py-4 on main.
 *
 *   md+ (≥ 768px)   Tablet portrait and above — DESKTOP BEHAVIOR.
 *                    - Sidebar: persistent 240px grid track.
 *                    - Layout: grid-cols-[240px_1fr], same as before
 *                      this responsive refactor.
 *                    - Padding: px-7 py-6 on main (unchanged).
 *
 * Module pages already key their internal `lg:grid-cols-4` layouts off
 * `lg`; we deliberately don't touch that — the shell breakpoint is
 * `md`, the module-content breakpoint is `lg`, and they're orthogonal.
 *
 * Topbar stays naturally sticky: it lives outside the scroll container
 * (main has overflow-auto, Topbar is its sibling), so it never moves
 * when content scrolls.
 *
 * ─────────────────────────────────────────────────────────────────
 * Field mode
 * ─────────────────────────────────────────────────────────────────
 *
 * `data-field="true"` on the root activates styles/field-mode.css
 * overrides (high-contrast tokens + 44px tap targets). State is
 * session-only via AppShellProvider. Topbar owns the toggle UI.
 */
export function AppShell() {
  return (
    <AppShellProvider>
      <AppShellInner />
    </AppShellProvider>
  );
}

function AppShellInner() {
  const { fieldMode } = useAppShell();
  return (
    <div
      data-field={fieldMode ? "true" : undefined}
      className="flex h-screen flex-col bg-background md:grid md:grid-cols-[240px_1fr]"
    >
      <Sidebar className="hidden md:flex" />
      <MobileSidebar />
      <div className="flex min-w-0 flex-1 flex-col md:h-screen">
        <Topbar />
        <main className="flex-1 overflow-auto px-4 py-4 md:px-7 md:py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
