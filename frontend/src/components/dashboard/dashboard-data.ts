/**
 * Hardcoded mock data for the Home dashboard.
 *
 * Commit 2 is visual-only — every value here is deliberately static so the
 * mockup renders 1:1 without any backend wiring. Commit 3+ swap these for
 * useQuery() calls against /api/v1/dashboard/* endpoints (already planned
 * in api/v1/__init__.py).
 *
 * Colors use tailwind token classes, not raw hex, so a theme swap cascades
 * through every card. The `accentHex` escape hatch is for SVG strokes
 * (donut) where Tailwind classes don't apply.
 */

export interface PerfMetric {
  label: string;
  value: string;
  sub: string;
  barPct: number;
  /** Tailwind class name for the fill color — e.g. "bg-primary" */
  barClass: string;
  /** Tailwind class name for the value text — e.g. "text-primary" */
  valueClass: string;
}

export const perfMetrics: PerfMetric[] = [
  {
    label: "Monthly Savings",
    value: "$129,483",
    sub: "+12% vs Mar",
    barPct: 92,
    barClass: "bg-primary",
    valueClass: "text-primary",
  },
  {
    label: "Agent Uptime",
    value: "99.2%",
    sub: "17/17 agents live",
    barPct: 99,
    barClass: "bg-info",
    valueClass: "text-info",
  },
  {
    label: "Vista Sync Latency",
    value: "1.4s",
    sub: "p95 · SQL read",
    barPct: 86,
    barClass: "bg-accent",
    valueClass: "text-accent",
  },
  {
    label: "Token Spend",
    value: "$412",
    sub: "21% of monthly cap",
    barPct: 21,
    barClass: "bg-warning",
    valueClass: "text-warning",
  },
];

export interface ChartPoint {
  m: string;
  v: number;
  highlight?: boolean;
}

export const chartData: ChartPoint[] = [
  { m: "Nov", v: 68 },
  { m: "Dec", v: 82 },
  { m: "Jan", v: 94 },
  { m: "Feb", v: 108 },
  { m: "Mar", v: 121 },
  { m: "Apr", v: 129, highlight: true },
];

export type Tone = "good" | "bad" | "warn" | "info" | "neutral";

export interface FleetInsight {
  count: number;
  label: string;
  tone: Tone;
  highlight?: boolean;
}

export const fleetInsights: FleetInsight[] = [
  { count: 67, label: "Under Utilized", tone: "neutral" },
  { count: 19, label: "Excessive Idling", tone: "warn" },
  { count: 14, label: "Good Standing", tone: "good" },
  { count: 5, label: "Issues Reported", tone: "bad", highlight: true },
  { count: 4, label: "Breakdowns", tone: "bad" },
  { count: 355, label: "Geofence Alerts", tone: "info" },
  { count: 41, label: "No Activity", tone: "neutral" },
];

export interface DonutSlice {
  label: string;
  count: number;
  /** Raw hex because SVG stroke isn't Tailwind-friendly. */
  color: string;
}

export const donutSlices: DonutSlice[] = [
  { label: "Critical", count: 13, color: "hsl(0 84% 60%)" },
  { label: "Monitor", count: 17, color: "hsl(38 92% 50%)" },
  { label: "Minor", count: 9, color: "hsl(48 96% 58%)" },
  { label: "Unknown", count: 0, color: "hsl(215 20% 75%)" },
];

export type Severity = "crit" | "warn" | "ok";

export interface AgentAlert {
  agent: string;
  asset: string;
  time: string;
  msg: string;
  severity: Severity;
}

export const agentAlerts: AgentAlert[] = [
  {
    agent: "predictive_maintenance",
    asset: "PM237-10 FT PD",
    time: "Apr 20 · 1:38 PM",
    msg:
      "Left material height sonic sensor: abnormal frequency — schedule inspection within 48h.",
    severity: "crit",
  },
  {
    agent: "downtime_cost",
    asset: "BD271 Midland Grading",
    time: "Apr 20 · 2:46 PM",
    msg: "High torque converter oil temperature trending 12% above baseline.",
    severity: "warn",
  },
  {
    agent: "work_order_sync",
    asset: "SGN0252",
    time: "Apr 20 · 3:14 PM",
    msg:
      "Transmission reverse switch erratic — WO-48812 opened in Vista (emwo).",
    severity: "warn",
  },
  {
    agent: "ap_po_sync",
    asset: "Invoice #INV-88241",
    time: "Apr 20 · 4:02 PM",
    msg:
      "Matched to PO-7712 (apvend). 3-way match complete — ready for AP posting.",
    severity: "ok",
  },
];
