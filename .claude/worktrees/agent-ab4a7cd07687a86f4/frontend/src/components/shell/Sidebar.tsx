import { NavLink } from "react-router-dom";

import { ScrollArea } from "@/components/ui/scroll-area";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

import { navGroups } from "./nav-config";

/**
 * Left sidebar. Uses react-router-dom <NavLink> so active state is
 * driven by the URL, not by prop-passing. Emerald accent on active,
 * matching the primary token.
 *
 * The visual content lives in <SidebarBody> so the same tree can be
 * dropped into the mobile <Sheet> drawer (see MobileSidebar.tsx)
 * without any rendering drift between desktop and mobile.
 */
export function Sidebar({ className }: { className?: string }) {
  return (
    <aside
      className={cn(
        "flex h-screen flex-col border-r border-border bg-sidebar text-sidebar-foreground",
        className,
      )}
    >
      <SidebarBody />
    </aside>
  );
}

/**
 * Sidebar inner content — brand, tenant chip, nav, status footer.
 * Exported so MobileSidebar can render an identical body inside a
 * Sheet panel. Anything navigation-related goes here, not in the
 * desktop wrapper above.
 */
export function SidebarBody({ onNavigate }: { onNavigate?: () => void }) {
  const user = useAuth((s) => s.user);

  return (
    <div className="flex h-full flex-col">
      {/* Brand */}
      <div className="px-5 pt-5">
        <div className="text-[17px] font-semibold tracking-tight">
          FieldBridge<span className="text-warning">.</span>
        </div>
      </div>

      {/* Tenant chip — static for now. Clicking it will open the
          TenantSwitcher once we support multi-tenant users. */}
      {user && (
        <div className="mx-4 mt-4 rounded-lg border border-border bg-card px-3 py-2">
          <div className="text-[13px] font-semibold leading-tight">
            {user.tenant.name}
          </div>
          <div className="mt-0.5 text-[11px] text-muted-foreground">
            {[user.department, user.role].filter(Boolean).join(" · ")}
          </div>
        </div>
      )}

      {/* Nav — scrollable so long groups don't break layout */}
      <ScrollArea className="mt-4 flex-1">
        <nav className="pb-4">
          {navGroups.map((group) => (
            <div key={group.heading} className="mt-4 first:mt-0">
              <div className="px-5 pb-1.5 text-[10px] font-semibold uppercase tracking-[1px] text-sidebar-muted">
                {group.heading}
              </div>
              {group.items.map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end
                    onClick={onNavigate}
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-3 border-l-[3px] border-transparent px-[17px] py-1.5 text-[13px] transition-colors",
                        isActive
                          ? "border-l-primary bg-primary/5 font-semibold text-foreground"
                          : "text-sidebar-foreground hover:bg-muted",
                      )
                    }
                  >
                    <Icon className="h-4 w-4 text-muted-foreground" />
                    <span className="truncate">{item.label}</span>
                  </NavLink>
                );
              })}
            </div>
          ))}
        </nav>
      </ScrollArea>

      {/* Status footer */}
      <div className="flex items-center gap-2 border-t border-border px-5 py-3 text-[11px] text-muted-foreground">
        <span className="relative inline-block h-2 w-2 rounded-full bg-primary">
          <span className="absolute inset-[-3px] rounded-full bg-primary/25" />
        </span>
        All systems operational
      </div>
    </div>
  );
}
