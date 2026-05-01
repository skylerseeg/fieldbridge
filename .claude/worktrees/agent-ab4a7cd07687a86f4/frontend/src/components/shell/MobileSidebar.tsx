import * as React from "react";
import { useLocation } from "react-router-dom";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from "@/components/ui/sheet";

import { useAppShell } from "./app-shell-context";
import { SidebarBody } from "./Sidebar";

/**
 * Mobile sidebar drawer (< md). Lives outside the AppShell grid as a
 * portal-mounted Sheet so it adds nothing to the layout when closed.
 *
 *   - Trigger: Topbar's hamburger button (calls setSidebarOpen(true)).
 *   - Close paths: tap overlay, Esc, or any NavLink click — the
 *     navigation listener below auto-closes on pathname change.
 *   - Width: 280px (Sheet default for side="left"), wider than the
 *     desktop's 240px to give a glove-and-thumb hit target.
 *   - Background: bg-sidebar overrides the Sheet's default bg-card so
 *     the panel matches the desktop sidebar's off-white treatment.
 *
 * SidebarBody is the same component the desktop <Sidebar> wraps —
 * single source of truth for nav structure.
 */
export function MobileSidebar() {
  const { sidebarOpen, setSidebarOpen } = useAppShell();
  const { pathname } = useLocation();

  // Close the drawer whenever the user navigates. Initial mount also
  // fires this (open is already false → React bails on the no-op).
  React.useEffect(() => {
    setSidebarOpen(false);
  }, [pathname, setSidebarOpen]);

  return (
    <Sheet open={sidebarOpen} onOpenChange={setSidebarOpen}>
      <SheetContent
        side="left"
        showClose={false}
        className="bg-sidebar text-sidebar-foreground p-0"
        data-mobile-sidebar=""
      >
        {/* Radix Dialog requires a Title + Description for screen readers
            even when visually hidden. The visible brand inside SidebarBody
            already announces "FieldBridge", but Radix expects a Title at
            the Dialog root level — sr-only here keeps the chrome clean. */}
        <SheetTitle className="sr-only">Navigation</SheetTitle>
        <SheetDescription className="sr-only">
          FieldBridge module navigation
        </SheetDescription>
        <SidebarBody onNavigate={() => setSidebarOpen(false)} />
      </SheetContent>
    </Sheet>
  );
}
