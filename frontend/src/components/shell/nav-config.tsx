import {
  Activity,
  Bot,
  Briefcase,
  ClipboardList,
  Clock,
  DollarSign,
  FileSearch,
  Gauge,
  Hash,
  Home,
  Image as ImageIcon,
  LayoutDashboard,
  Mail,
  Receipt,
  Search,
  ShieldAlert,
  Sparkles,
  Wrench,
  type LucideIcon,
} from "lucide-react";

/**
 * Sidebar nav definition. Single source of truth for both sidebar rendering
 * and any "active section" lookup we add later. Paths must match routes.tsx
 * exactly — the NavLink active state relies on that.
 *
 * ADMIN group intentionally omitted. VANCON-Technologies operator tooling
 * (Tenants, Users & RBAC, Metering) will live in a separate frontend
 * mounted at a different domain, not here. Don't add it back unless
 * you mean to change that architectural decision.
 */
export interface NavItem {
  label: string;
  icon: LucideIcon;
  to: string;
}

export interface NavGroup {
  heading: string;
  items: NavItem[];
}

export const navGroups: NavGroup[] = [
  {
    heading: "MAIN MENU",
    items: [
      { label: "Home", icon: Home, to: "/dashboard" },
      { label: "Executive Dashboard", icon: LayoutDashboard, to: "/executive-dashboard" },
      { label: "Activity Feed", icon: Activity, to: "/activity-feed" },
    ],
  },
  {
    heading: "OPERATIONS",
    items: [
      { label: "Equipment", icon: Wrench, to: "/equipment" },
      { label: "Work Orders", icon: ClipboardList, to: "/work-orders" },
      { label: "Timecards", icon: Clock, to: "/timecards" },
      { label: "Jobs", icon: Briefcase, to: "/jobs" },
    ],
  },
  {
    heading: "FINANCE",
    items: [
      { label: "Fleet P&L", icon: DollarSign, to: "/fleet-pnl" },
      { label: "Vendors / AP", icon: Receipt, to: "/vendors" },
      { label: "Cost Coding", icon: Hash, to: "/cost-coding" },
    ],
  },
  {
    heading: "INTELLIGENCE",
    items: [
      { label: "Predictive Maint.", icon: Gauge, to: "/predictive-maintenance" },
      { label: "Recommendations", icon: Sparkles, to: "/recommendations" },
      { label: "Bids", icon: FileSearch, to: "/bids" },
      { label: "Proposals", icon: Mail, to: "/proposals" },
    ],
  },
  {
    heading: "KNOWLEDGE",
    items: [
      { label: "Project Search", icon: Search, to: "/project-search" },
      { label: "Media Library", icon: ImageIcon, to: "/media-library" },
      { label: "Safety", icon: ShieldAlert, to: "/safety" },
    ],
  },
];

// Exported separately so an Agents module can reuse this icon later
// without re-importing from lucide. (Not in nav today.)
export const Icons = { Bot };
