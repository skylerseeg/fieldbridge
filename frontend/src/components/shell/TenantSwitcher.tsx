import { ChevronDown } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/lib/auth";

/**
 * Tenant switcher — lives in the topbar.
 *
 * Today a FieldBridge user belongs to exactly one tenant (1:1 in
 * backend/app/models/user.py). The dropdown therefore only shows the
 * current tenant and a dimmed hint. When the MSP tier lands (CyberAdvisors
 * managing N customer tenants → user_tenants join table), wire the list
 * here; the trigger and layout do not need to change.
 */
export function TenantSwitcher() {
  const user = useAuth((s) => s.user);
  if (!user) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex flex-col items-start focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-md px-1">
        <span className="text-[11px] uppercase tracking-[0.5px] text-muted-foreground">
          Tenant
        </span>
        <span className="flex max-w-[160px] items-center gap-1 truncate text-lg font-semibold tracking-tight lg:max-w-none">
          {user.tenant.name}
          <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
        </span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-[220px]">
        <DropdownMenuLabel>Your tenants</DropdownMenuLabel>
        <DropdownMenuItem className="font-medium">
          <span className="mr-2 inline-block h-2 w-2 rounded-full bg-primary" />
          {user.tenant.name}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled className="text-xs text-muted-foreground">
          Multi-tenant switching arrives with the MSP tier.
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
