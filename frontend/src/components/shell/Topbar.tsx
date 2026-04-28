import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Contrast, LogOut, Menu, Search } from "lucide-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

import { useAppShell } from "./app-shell-context";
import { TenantSwitcher } from "./TenantSwitcher";

/**
 * Top bar — tenant switcher on the left, search / auto-refresh / user
 * chip on the right.
 *
 * Mobile additions (< md):
 *   - Hamburger button (left of the tenant switcher) opens the mobile
 *     sidebar drawer via useAppShell().
 *   - Search input is hidden (already was: hidden md:block).
 *   - Auto-refresh label collapses to icon-only spacing — the Switch
 *     itself stays for one-handed reach.
 *
 * Field-mode toggle (any breakpoint):
 *   - Contrast icon button. Adds data-field="true" to the AppShell
 *     root, which scopes styles/field-mode.css overrides (high contrast
 *     + 44px tap targets). Session-only state — see app-shell-context.
 *
 * The Auto Refresh toggle is UI-only for now. Commit 2 does not wire it
 * to any query-invalidation logic; that lives with whatever module needs
 * it (e.g. Dashboard polling every 30s when on).
 *
 * Search is a placeholder input. Global-search is out of scope for this
 * migration — we'll bolt it on after Commit 5 lands.
 */
export function Topbar() {
  const navigate = useNavigate();
  const user = useAuth((s) => s.user);
  const logout = useAuth((s) => s.logout);
  const { setSidebarOpen, fieldMode, setFieldMode } = useAppShell();
  const [autoRefresh, setAutoRefresh] = useState(true);

  const handleSignOut = () => {
    logout();
    navigate("/login", { replace: true });
  };

  const initials =
    user?.email
      ?.split("@")[0]
      ?.split(/[._-]/)
      .filter(Boolean)
      .slice(0, 2)
      .map((p) => p[0]?.toUpperCase())
      .join("") ?? "?";

  return (
    <header className="flex items-center justify-between gap-3 border-b border-border bg-background px-4 py-3.5 md:px-7">
      <div className="flex min-w-0 items-center gap-2">
        {/* Hamburger — mobile only. 44x44 hit target for gloves. */}
        <button
          type="button"
          onClick={() => setSidebarOpen(true)}
          aria-label="Open navigation"
          className="inline-flex h-11 w-11 items-center justify-center rounded-md text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:hidden"
        >
          <Menu className="h-5 w-5" aria-hidden="true" />
        </button>
        <TenantSwitcher />
      </div>

      <div className="flex items-center gap-2 md:gap-3">
        {/* Search */}
        <div className="relative hidden md:block">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search jobs, equipment, vendors…"
            className="w-[180px] pl-9 lg:w-[300px]"
          />
        </div>

        {/* Field-mode toggle — always visible. Pressed state is the
            ARIA accessibility hook; the visual emerald tint just
            mirrors that for sighted users. */}
        <button
          type="button"
          onClick={() => setFieldMode(!fieldMode)}
          aria-pressed={fieldMode}
          aria-label={
            fieldMode ? "Disable field mode" : "Enable field mode (high contrast)"
          }
          title={fieldMode ? "Field mode on" : "Field mode off"}
          className={cn(
            "inline-flex h-11 w-11 items-center justify-center rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            fieldMode
              ? "bg-primary/10 text-primary"
              : "text-muted-foreground hover:bg-muted hover:text-foreground",
          )}
        >
          <Contrast className="h-5 w-5" aria-hidden="true" />
        </button>

        {/* Auto-refresh */}
        <div className="flex items-center gap-2">
          <Switch
            checked={autoRefresh}
            onCheckedChange={setAutoRefresh}
            aria-label="Auto refresh"
          />
          <span className="hidden text-sm font-medium text-foreground lg:inline">
            Auto Refresh
          </span>
        </div>

        {/* User chip */}
        {user && (
          <DropdownMenu>
            <DropdownMenuTrigger className="flex items-center gap-2 rounded-full border border-border bg-card py-1 pl-1 pr-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <Avatar className="h-7 w-7">
                <AvatarFallback>{initials}</AvatarFallback>
              </Avatar>
              <span className="hidden max-w-[180px] truncate text-xs text-foreground sm:inline">
                {user.email}
              </span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-[220px]">
              <DropdownMenuLabel>
                <div className="text-xs font-normal text-muted-foreground">
                  Signed in as
                </div>
                <div className="truncate text-sm font-medium normal-case tracking-normal text-foreground">
                  {user.email}
                </div>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={handleSignOut}>
                <LogOut className="mr-2 h-4 w-4" />
                Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
    </header>
  );
}
