import { useMemo, useState } from "react";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import {
  Activity,
  AlertOctagon,
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  CalendarClock,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Circle,
  CircleDollarSign,
  Cog,
  Droplets,
  Eye,
  GitBranch,
  Hammer,
  Hourglass,
  Info,
  Sparkles,
  Truck,
  Wrench,
  XCircle,
  Zap,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

import {
  acknowledgePrediction,
  completePrediction,
  dismissPrediction,
  fetchPredictiveMaintenanceInsights,
  fetchPredictiveMaintenanceList,
  fetchPredictiveMaintenanceSummary,
  type FailureMode,
  type ListParams,
  type MaintSource,
  type MaintStatus,
  type PredictionListResponse,
  type PredictionListRow,
  type RiskTier,
  type SortDir,
  type SortField,
} from "./predictive-maintenance-api";

/**
 * Predictive Maintenance module — Phase 5 page.
 *
 * Layout:
 *   ┌── 4 KPI tiles (fleet risk) ──────────────────────┐ ┌── Recommendations
 *   │  Open · Critical · Overdue · Exposure $          │ │   (right rail)
 *   ├── Tabs: Overview · List · Insights ──────────────┤ │
 *   │  Overview: risk mix bar + status / money / aging │ │
 *   │  List:     paginated TanStack table with         │ │
 *   │            row-level acknowledge/complete/       │ │
 *   │            dismiss mutations (optimistic)        │ │
 *   │  Insights: risk + status + failure-mode mix,     │ │
 *   │            source split (PM-due vs AI), top      │ │
 *   │            equipment exposure, top by repair $,  │ │
 *   │            recent completions                    │ │
 *   └──────────────────────────────────────────────────┘ └──────────────────
 *
 * One row per maintenance prediction for an equipment unit. Two
 * orthogonal classifications:
 *   - **RiskTier** (critical / high / medium / low) — drives
 *     crit / warn / info / neutral tone.
 *   - **MaintSource** (pm_overdue / failure_prediction) — calendar-
 *     based vs. AI-derived; drives icon mapping but **not** tone (so
 *     a critical PM and a critical AI prediction read with the same
 *     visual weight).
 *
 * Plus a free-form **FailureMode** category and a workflow
 * **MaintStatus** (open / acknowledged / scheduled / completed /
 * dismissed). "Schedule" is intentionally **not** a row-level
 * action — it needs a date picker that fits in the detail drawer
 * (Phase 6). Row-level actions are limited to Acknowledge, Complete,
 * Dismiss.
 *
 * Severity → token mapping (no new colors):
 *   primary  = good / dominant healthy bucket (clean queue, completed)
 *   info     = neutral fact (low risk, AI source, ack'd in flight)
 *   warning  = caution (high risk, scheduled, hydraulic/structural)
 *   critical = alert (critical risk, overdue, electrical hazard)
 *
 * Mutations flip only `status` (and `scheduled_for` for schedule, not
 * exposed at row level here), so optimistic updates are safe — same
 * `onMutate` cancel-snapshot-set pattern as the recommendations page.
 */

// ── Severity / token maps (no new colors) ────────────────────────────

type Tone = "good" | "info" | "warn" | "crit" | "neutral";

const toneStyles: Record<
  Tone,
  { border: string; bg: string; text: string; fill: string }
> = {
  good: {
    border: "border-l-primary",
    bg: "bg-primary/10",
    text: "text-primary",
    fill: "hsl(var(--primary))",
  },
  info: {
    border: "border-l-info",
    bg: "bg-info/10",
    text: "text-info",
    fill: "hsl(var(--info))",
  },
  warn: {
    border: "border-l-warning",
    bg: "bg-warning/10",
    text: "text-warning",
    fill: "hsl(var(--warning))",
  },
  crit: {
    border: "border-l-critical",
    bg: "bg-critical/10",
    text: "text-critical",
    fill: "hsl(var(--critical))",
  },
  neutral: {
    border: "border-l-accent",
    bg: "bg-muted",
    text: "text-muted-foreground",
    fill: "hsl(var(--accent))",
  },
};

const riskStyles: Record<
  RiskTier,
  { tone: Tone; label: string; Icon: typeof AlertOctagon }
> = {
  critical: { tone: "crit", label: "Critical", Icon: AlertOctagon },
  high: { tone: "warn", label: "High", Icon: AlertTriangle },
  medium: { tone: "info", label: "Medium", Icon: Info },
  low: { tone: "neutral", label: "Low", Icon: Circle },
};

const failureStyles: Record<
  FailureMode,
  { tone: Tone; label: string; Icon: typeof Cog }
> = {
  engine: { tone: "warn", label: "Engine", Icon: Cog },
  hydraulic: { tone: "info", label: "Hydraulic", Icon: Droplets },
  electrical: { tone: "crit", label: "Electrical", Icon: Zap },
  drivetrain: { tone: "warn", label: "Drivetrain", Icon: GitBranch },
  structural: { tone: "info", label: "Structural", Icon: Wrench },
  other: { tone: "neutral", label: "Other", Icon: Hammer },
};

const sourceStyles: Record<
  MaintSource,
  { tone: Tone; label: string; Icon: typeof CalendarClock }
> = {
  pm_overdue: { tone: "warn", label: "PM-due", Icon: CalendarClock },
  failure_prediction: { tone: "info", label: "AI-predict", Icon: Activity },
};

const statusStyles: Record<
  MaintStatus,
  { tone: Tone; label: string }
> = {
  open: { tone: "info", label: "Open" },
  acknowledged: { tone: "info", label: "Ack'd" },
  scheduled: { tone: "warn", label: "Scheduled" },
  completed: { tone: "good", label: "Completed" },
  dismissed: { tone: "neutral", label: "Dismissed" },
};

// Display order for stacks.
const RISK_ORDER: RiskTier[] = ["critical", "high", "medium", "low"];
const STATUS_ORDER: MaintStatus[] = [
  "open",
  "acknowledged",
  "scheduled",
  "completed",
  "dismissed",
];
const FAILURE_ORDER: FailureMode[] = [
  "engine",
  "hydraulic",
  "electrical",
  "drivetrain",
  "structural",
  "other",
];
const SOURCE_ORDER: MaintSource[] = ["pm_overdue", "failure_prediction"];

// Query key factory.
const keys = {
  all: ["predictive-maintenance"] as const,
  summary: () => [...keys.all, "summary"] as const,
  list: (params: ListParams) => [...keys.all, "list", params] as const,
  insights: (topN: number) => [...keys.all, "insights", topN] as const,
};

// ──────────────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────────────

export function PredictiveMaintenancePage() {
  return (
    <div className="p-6 lg:p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">
          Predictive Maintenance
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Calendar PMs and AI-derived failure predictions on the active
          fleet — prioritized by risk, repair cost, and time-to-due.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        <div className="space-y-6 lg:col-span-3">
          <KpiTiles />
          <ContentTabs />
        </div>
        <aside className="lg:col-span-1">
          <RecommendationsRail />
        </aside>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// KPI tiles
// ──────────────────────────────────────────────────────────────────────

function KpiTiles() {
  const { data, isLoading, isError } = useQuery({
    queryKey: keys.summary(),
    queryFn: fetchPredictiveMaintenanceSummary,
  });

  // Four risk-oriented tiles. Severity adapts:
  //   - Open: 0 = good · ≤10 = info · ≤25 = warn · else crit.
  //   - Critical: 0 = good · ≤2 = info · ≤5 = warn · else crit.
  //   - Overdue: 0 = good · ≤3 = info · ≤7 = warn · else crit.
  //   - Exposure $: info / neutral.
  const tiles = useMemo(() => {
    if (!data) return [];

    const openTone: Tone =
      data.open_count === 0
        ? "good"
        : data.open_count <= 10
          ? "info"
          : data.open_count <= 25
            ? "warn"
            : "crit";

    const critTone: Tone =
      data.open_critical_count === 0
        ? "good"
        : data.open_critical_count <= 2
          ? "info"
          : data.open_critical_count <= 5
            ? "warn"
            : "crit";

    const overdueTone: Tone =
      data.open_overdue_count === 0
        ? "good"
        : data.open_overdue_count <= 3
          ? "info"
          : data.open_overdue_count <= 7
            ? "warn"
            : "crit";

    return [
      {
        key: "open",
        tone: openTone,
        Icon: Truck,
        value: data.open_count.toLocaleString(),
        label: "Open predictions",
        sub: `${data.distinct_equipment.toLocaleString()} units · ${data.scheduled_count.toLocaleString()} scheduled`,
      },
      {
        key: "critical",
        tone: critTone,
        Icon: AlertOctagon,
        value: data.open_critical_count.toLocaleString(),
        label: "Critical risk",
        sub:
          data.critical_count > 0
            ? `${data.critical_count.toLocaleString()} critical lifetime`
            : "no critical history",
      },
      {
        key: "overdue",
        tone: overdueTone,
        Icon: Hourglass,
        value: data.open_overdue_count.toLocaleString(),
        label: "Overdue",
        sub: `${data.pm_overdue_count.toLocaleString()} PM · ${data.failure_prediction_count.toLocaleString()} AI`,
      },
      {
        key: "exposure",
        tone:
          data.total_estimated_exposure > 0
            ? ("info" as Tone)
            : ("neutral" as Tone),
        Icon: CircleDollarSign,
        value:
          data.total_estimated_exposure > 0
            ? formatMoney(data.total_estimated_exposure)
            : "—",
        label: "Estimated exposure",
        sub:
          data.total_estimated_downtime_hours > 0
            ? `${formatHours(data.total_estimated_downtime_hours)} downtime`
            : "no exposure data",
      },
    ];
  }, [data]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Risk snapshot</CardTitle>
          <CardDescription>
            Fleet-wide rollup · pulled from the predictive-maintenance queue
          </CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          {data && (
            <>
              <Badge variant="mono">
                {data.distinct_equipment.toLocaleString()} units
              </Badge>
              <Badge variant="mono">
                {data.distinct_failure_modes.toLocaleString()} modes
              </Badge>
              <Badge variant="mono">
                {data.completed_count.toLocaleString()} resolved
              </Badge>
            </>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {isError && <ErrorBlock message="Couldn't load summary." />}
        {isLoading && <SkeletonGrid count={4} />}
        {data && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {tiles.map((t) => {
              const s = toneStyles[t.tone];
              return (
                <div
                  key={t.key}
                  className={cn(
                    "flex flex-col gap-1.5 rounded-lg border border-border border-l-4 bg-card px-4 py-3.5",
                    s.border,
                  )}
                >
                  <div
                    className={cn(
                      "flex h-7 w-7 items-center justify-center rounded-md",
                      s.bg,
                    )}
                  >
                    <t.Icon className={cn("h-3.5 w-3.5", s.text)} />
                  </div>
                  <div className="font-mono text-2xl font-semibold tabular-nums">
                    {t.value}
                  </div>
                  <div className="text-xs font-medium">{t.label}</div>
                  <div className="text-[11px] text-muted-foreground">
                    {t.sub}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Tabs
// ──────────────────────────────────────────────────────────────────────

function ContentTabs() {
  return (
    <Card>
      <Tabs defaultValue="overview" className="w-full">
        <CardHeader className="space-y-3">
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="list">List</TabsTrigger>
            <TabsTrigger value="insights">Insights</TabsTrigger>
          </TabsList>
        </CardHeader>
        <CardContent>
          <TabsContent value="overview" className="mt-0">
            <OverviewTab />
          </TabsContent>
          <TabsContent value="list" className="mt-0">
            <ListTab />
          </TabsContent>
          <TabsContent value="insights" className="mt-0">
            <InsightsTab />
          </TabsContent>
        </CardContent>
      </Tabs>
    </Card>
  );
}

// ── Overview ─────────────────────────────────────────────────────────

function OverviewTab() {
  const summary = useQuery({
    queryKey: keys.summary(),
    queryFn: fetchPredictiveMaintenanceSummary,
  });
  const insights = useQuery({
    queryKey: keys.insights(10),
    queryFn: () => fetchPredictiveMaintenanceInsights(10),
  });

  if (summary.isError || insights.isError) {
    return <ErrorBlock message="Couldn't load overview." />;
  }
  if (
    summary.isLoading ||
    insights.isLoading ||
    !summary.data ||
    !insights.data
  ) {
    return <SkeletonBlock height="h-64" />;
  }

  const s = summary.data;
  const i = insights.data;

  // Headline: risk-tier mix.
  const riskChart = RISK_ORDER.map((k) => ({
    key: k,
    label: riskStyles[k].label,
    value: i.risk_tier_breakdown[k],
    tone: riskStyles[k].tone,
  }));

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
      <div className="md:col-span-2">
        <h3 className="text-sm font-semibold">Risk-tier mix</h3>
        <p className="mb-3 text-xs text-muted-foreground">
          Lifetime distribution across {s.total_predictions.toLocaleString()}{" "}
          predictions.
        </p>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={riskChart}
              margin={{ top: 8, right: 8, bottom: 8, left: 0 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="hsl(var(--border))"
              />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                stroke="hsl(var(--border))"
              />
              <YAxis
                allowDecimals={false}
                tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                stroke="hsl(var(--border))"
              />
              <RechartsTooltip
                cursor={{ fill: "hsl(var(--muted))" }}
                contentStyle={{
                  background: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                formatter={(v: number) => v.toLocaleString()}
              />
              <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                {riskChart.map((d) => (
                  <Cell key={d.key} fill={toneStyles[d.tone].fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-semibold">Status</h3>
        <SummaryRow
          label="Open"
          value={s.open_count.toLocaleString()}
          sub={shareSub(s.open_count, s.total_predictions)}
        />
        <SummaryRow
          label="Acknowledged"
          value={s.acknowledged_count.toLocaleString()}
          sub={shareSub(s.acknowledged_count, s.total_predictions)}
        />
        <SummaryRow
          label="Scheduled"
          value={s.scheduled_count.toLocaleString()}
          sub={shareSub(s.scheduled_count, s.total_predictions)}
        />
        <SummaryRow
          label="Completed"
          value={s.completed_count.toLocaleString()}
          sub={shareSub(s.completed_count, s.total_predictions)}
        />
        <SummaryRow
          label="Dismissed"
          value={s.dismissed_count.toLocaleString()}
          sub={shareSub(s.dismissed_count, s.total_predictions)}
        />
        <div className="border-t border-border pt-3" />
        <h3 className="text-sm font-semibold">Money</h3>
        <SummaryRow
          label="Exposure"
          value={
            s.total_estimated_exposure > 0
              ? formatMoney(s.total_estimated_exposure)
              : "—"
          }
          sub={s.total_estimated_exposure > 0 ? "across open" : undefined}
        />
        <SummaryRow
          label="Downtime"
          value={
            s.total_estimated_downtime_hours > 0
              ? formatHours(s.total_estimated_downtime_hours)
              : "—"
          }
          sub={
            s.total_estimated_downtime_hours > 0 ? "estimated hrs" : undefined
          }
        />
        <div className="border-t border-border pt-3" />
        <h3 className="text-sm font-semibold">Aging (open)</h3>
        <SummaryRow
          label="Fresh (<7d)"
          value={i.aging_breakdown.fresh.toLocaleString()}
        />
        <SummaryRow
          label="Mature (7–30d)"
          value={i.aging_breakdown.mature.toLocaleString()}
        />
        <SummaryRow
          label="Stale (>30d)"
          value={i.aging_breakdown.stale.toLocaleString()}
        />
      </div>
    </div>
  );
}

function SummaryRow({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="font-mono text-sm font-semibold tabular-nums">
        {value}
        {sub && (
          <span className="ml-1.5 text-[11px] font-normal text-muted-foreground">
            {sub}
          </span>
        )}
      </span>
    </div>
  );
}

function shareSub(part: number, total: number): string | undefined {
  if (total <= 0 || part <= 0) return undefined;
  return `${((part / total) * 100).toFixed(0)}%`;
}

// ── List ─────────────────────────────────────────────────────────────

function ListTab() {
  const [search, setSearch] = useState("");
  const [risk, setRisk] = useState<RiskTier | "all">("all");
  const [mode, setMode] = useState<FailureMode | "all">("all");
  const [source, setSource] = useState<MaintSource | "all">("all");
  const [status, setStatus] = useState<MaintStatus | "all">("open");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [sorting, setSorting] = useState<SortingState>([
    { id: "risk_tier", desc: true },
  ]);

  const sortBy = (sorting[0]?.id ?? "risk_tier") as SortField;
  const sortDir: SortDir = sorting[0]?.desc ? "desc" : "asc";

  const params: ListParams = useMemo(
    () => ({
      page,
      page_size: pageSize,
      sort_by: sortBy,
      sort_dir: sortDir,
      ...(search.trim() ? { search: search.trim() } : {}),
      ...(risk !== "all" ? { risk_tier: risk } : {}),
      ...(mode !== "all" ? { failure_mode: mode } : {}),
      ...(source !== "all" ? { source } : {}),
      ...(status !== "all" ? { status } : {}),
    }),
    [page, pageSize, sortBy, sortDir, search, risk, mode, source, status],
  );

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: keys.list(params),
    queryFn: () => fetchPredictiveMaintenanceList(params),
    placeholderData: keepPreviousData,
  });

  const actions = usePredictionActions(params);

  const columns = useMemo<ColumnDef<PredictionListRow>[]>(
    () => [
      {
        accessorKey: "equipment_label",
        header: "Equipment",
        cell: ({ row }) => {
          const f = failureStyles[row.original.failure_mode];
          const ts = toneStyles[f.tone];
          return (
            <div className="flex flex-col gap-0.5">
              <span
                className="line-clamp-2 text-xs font-medium"
                title={row.original.equipment_label}
              >
                {row.original.equipment_label}
              </span>
              <span className="font-mono text-[10px] text-muted-foreground">
                {row.original.equipment_id}
              </span>
              <span
                className={cn(
                  "mt-0.5 inline-flex w-fit items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                  ts.bg,
                  ts.text,
                )}
              >
                <f.Icon className="h-3 w-3" />
                {f.label}
              </span>
            </div>
          );
        },
      },
      {
        accessorKey: "risk_tier",
        header: "Risk",
        cell: ({ row }) => {
          const r = riskStyles[row.original.risk_tier];
          const ts = toneStyles[r.tone];
          return (
            <span
              className={cn(
                "inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
                ts.bg,
                ts.text,
              )}
            >
              <r.Icon className="h-3 w-3" />
              {r.label}
            </span>
          );
        },
      },
      {
        accessorKey: "days_until_due",
        header: "Due",
        cell: ({ row }) => {
          const r = row.original;
          if (r.days_until_due === null) {
            return <span className="text-xs text-muted-foreground">—</span>;
          }
          // Color the day count by urgency.
          const dueTone: Tone =
            r.days_until_due < 0
              ? "crit"
              : r.days_until_due <= 7
                ? "warn"
                : r.days_until_due <= 30
                  ? "info"
                  : "neutral";
          const ts = toneStyles[dueTone];
          const refDate =
            r.source === "pm_overdue" ? r.pm_due_date : r.predicted_failure_date;
          return (
            <div className="flex flex-col gap-0.5">
              <span className={cn("font-mono text-xs tabular-nums", ts.text)}>
                {r.days_until_due < 0
                  ? `${Math.abs(r.days_until_due).toFixed(0)}d overdue`
                  : `in ${r.days_until_due.toFixed(0)}d`}
              </span>
              {refDate && (
                <span className="text-[10px] text-muted-foreground">
                  {formatDate(refDate)}
                </span>
              )}
            </div>
          );
        },
      },
      {
        accessorKey: "estimated_repair_cost",
        header: "Repair $",
        cell: ({ row }) => {
          const c = row.original.estimated_repair_cost;
          if (c === null || c === 0) {
            return <span className="text-xs text-muted-foreground">—</span>;
          }
          return (
            <div className="flex flex-col gap-0.5">
              <span className="font-mono text-xs tabular-nums">
                {formatMoney(c)}
              </span>
              {row.original.estimated_downtime_hours !== null &&
                row.original.estimated_downtime_hours > 0 && (
                  <span className="text-[10px] text-muted-foreground">
                    {formatHours(row.original.estimated_downtime_hours)} hrs
                  </span>
                )}
            </div>
          );
        },
      },
      {
        id: "source",
        accessorKey: "source",
        header: "Source",
        enableSorting: false,
        cell: ({ row }) => {
          const sc = sourceStyles[row.original.source];
          const ts = toneStyles[sc.tone];
          return (
            <span
              className={cn(
                "inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
                ts.bg,
                ts.text,
              )}
            >
              <sc.Icon className="h-3 w-3" />
              {sc.label}
            </span>
          );
        },
      },
      {
        id: "status",
        accessorKey: "status",
        header: "Status",
        enableSorting: false,
        cell: ({ row }) => {
          const st = statusStyles[row.original.status];
          const ts = toneStyles[st.tone];
          return (
            <span
              className={cn(
                "inline-flex w-fit items-center rounded-full px-2 py-0.5 text-[11px] font-medium",
                ts.bg,
                ts.text,
              )}
            >
              {st.label}
            </span>
          );
        },
      },
      {
        id: "actions",
        header: "Actions",
        enableSorting: false,
        cell: ({ row }) => {
          const r = row.original;
          const isPending =
            actions.acknowledge.isPending ||
            actions.complete.isPending ||
            actions.dismiss.isPending;
          // Resolved rows can't be re-acted on from the table.
          if (r.status === "completed" || r.status === "dismissed") {
            return (
              <span className="text-[11px] text-muted-foreground">
                {r.status === "completed" ? "completed" : "dismissed"}
              </span>
            );
          }
          return (
            <div className="flex items-center gap-1">
              {r.status === "open" && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={isPending}
                  onClick={() => actions.acknowledge.mutate({ id: r.id })}
                  title="Acknowledge"
                >
                  <Eye className="h-3 w-3" />
                  <span className="ml-1 hidden sm:inline">Ack</span>
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                disabled={isPending}
                onClick={() => actions.complete.mutate({ id: r.id })}
                title="Mark completed"
              >
                <CheckCircle2 className="h-3 w-3" />
                <span className="ml-1 hidden sm:inline">Done</span>
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={isPending}
                onClick={() => actions.dismiss.mutate({ id: r.id })}
                title="Dismiss"
              >
                <XCircle className="h-3 w-3" />
              </Button>
            </div>
          );
        },
      },
    ],
    [actions],
  );

  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    manualPagination: true,
    onSortingChange: (updater) => {
      setSorting(updater);
      setPage(1);
    },
    state: { sorting },
  });

  const total = data?.total ?? 0;
  const lastPage = Math.max(1, Math.ceil(total / pageSize));
  const startRow = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const endRow = Math.min(page * pageSize, total);

  return (
    <div className="space-y-3">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          placeholder="Search equipment, action, code…"
          className="w-full sm:w-72"
        />
        <Select<RiskTier | "all">
          value={risk}
          onChange={(v) => {
            setRisk(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All risks" },
            { value: "critical", label: "Critical" },
            { value: "high", label: "High" },
            { value: "medium", label: "Medium" },
            { value: "low", label: "Low" },
          ]}
        />
        <Select<FailureMode | "all">
          value={mode}
          onChange={(v) => {
            setMode(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All modes" },
            { value: "engine", label: "Engine" },
            { value: "hydraulic", label: "Hydraulic" },
            { value: "electrical", label: "Electrical" },
            { value: "drivetrain", label: "Drivetrain" },
            { value: "structural", label: "Structural" },
            { value: "other", label: "Other" },
          ]}
        />
        <Select<MaintSource | "all">
          value={source}
          onChange={(v) => {
            setSource(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All sources" },
            { value: "pm_overdue", label: "PM-due" },
            { value: "failure_prediction", label: "AI-predict" },
          ]}
        />
        <Select<MaintStatus | "all">
          value={status}
          onChange={(v) => {
            setStatus(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All statuses" },
            { value: "open", label: "Open" },
            { value: "acknowledged", label: "Acknowledged" },
            { value: "scheduled", label: "Scheduled" },
            { value: "completed", label: "Completed" },
            { value: "dismissed", label: "Dismissed" },
          ]}
        />
        {isFetching && (
          <span className="text-[11px] text-muted-foreground">refreshing…</span>
        )}
      </div>

      {isError && <ErrorBlock message="Couldn't load predictions." />}
      {actions.error && (
        <ErrorBlock message={`Action failed — ${actions.error}`} />
      )}

      <div className="rounded-lg border border-border">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((hg) => (
              <TableRow key={hg.id}>
                {hg.headers.map((header) => {
                  const canSort = header.column.getCanSort();
                  const sort = header.column.getIsSorted();
                  return (
                    <TableHead key={header.id}>
                      {canSort ? (
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          className="inline-flex items-center gap-1 hover:text-foreground"
                        >
                          {flexRender(
                            header.column.columnDef.header,
                            header.getContext(),
                          )}
                          {sort === "asc" ? (
                            <ArrowUp className="h-3 w-3" />
                          ) : sort === "desc" ? (
                            <ArrowDown className="h-3 w-3" />
                          ) : (
                            <ArrowUpDown className="h-3 w-3 opacity-40" />
                          )}
                        </button>
                      ) : (
                        flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )
                      )}
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="text-center text-sm text-muted-foreground"
                >
                  Loading…
                </TableCell>
              </TableRow>
            ) : table.getRowModel().rows.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="text-center text-sm text-muted-foreground"
                >
                  No predictions match the current filters.
                </TableCell>
              </TableRow>
            ) : (
              table.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {total === 0
            ? "0 results"
            : `${startRow}–${endRow} of ${total.toLocaleString()}`}
        </span>
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1 || isLoading}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            Prev
          </Button>
          <span className="px-2 font-mono">
            {page} / {lastPage}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= lastPage || isLoading}
            onClick={() => setPage((p) => Math.min(lastPage, p + 1))}
          >
            Next
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}

// Lightweight token-styled select.
function Select<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as T)}
      className="h-9 rounded-md border border-input bg-card px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Mutation hook — acknowledge / complete / dismiss with optimistic
// updates. Schedule is intentionally NOT wired here — it needs a date
// picker that fits in the detail drawer (Phase 6).
//
// Each action only flips the row's `status` field, so we can safely
// apply the predicted state into the list cache immediately, then
// roll back on error and re-sync on settled.
// ──────────────────────────────────────────────────────────────────────

interface ActionContext {
  previousList: PredictionListResponse | undefined;
}

function usePredictionActions(params: ListParams) {
  const queryClient = useQueryClient();
  const listKey = keys.list(params);

  function applyStatus(id: string, nextStatus: MaintStatus): ActionContext {
    queryClient.cancelQueries({ queryKey: keys.all }).catch(() => {});
    const previousList =
      queryClient.getQueryData<PredictionListResponse>(listKey);
    if (previousList) {
      queryClient.setQueryData<PredictionListResponse>(listKey, {
        ...previousList,
        items: previousList.items.map((row) =>
          row.id === id ? { ...row, status: nextStatus } : row,
        ),
      });
    }
    return { previousList };
  }

  function rollback(ctx: ActionContext | undefined) {
    if (ctx?.previousList) {
      queryClient.setQueryData(listKey, ctx.previousList);
    }
  }

  function settle() {
    queryClient.invalidateQueries({ queryKey: keys.all });
  }

  const acknowledge = useMutation<
    unknown,
    Error,
    { id: string; note?: string },
    ActionContext
  >({
    mutationFn: ({ id, note }) => acknowledgePrediction(id, { note }),
    onMutate: ({ id }) => applyStatus(id, "acknowledged"),
    onError: (_err, _vars, ctx) => rollback(ctx),
    onSettled: settle,
  });

  const complete = useMutation<
    unknown,
    Error,
    { id: string; note?: string },
    ActionContext
  >({
    mutationFn: ({ id, note }) => completePrediction(id, { note }),
    onMutate: ({ id }) => applyStatus(id, "completed"),
    onError: (_err, _vars, ctx) => rollback(ctx),
    onSettled: settle,
  });

  const dismiss = useMutation<
    unknown,
    Error,
    { id: string; reason?: string },
    ActionContext
  >({
    mutationFn: ({ id, reason }) => dismissPrediction(id, { reason }),
    onMutate: ({ id }) => applyStatus(id, "dismissed"),
    onError: (_err, _vars, ctx) => rollback(ctx),
    onSettled: settle,
  });

  const error =
    acknowledge.error?.message ??
    complete.error?.message ??
    dismiss.error?.message ??
    null;

  return { acknowledge, complete, dismiss, error };
}

// ── Insights ─────────────────────────────────────────────────────────

function InsightsTab() {
  const { data, isLoading, isError } = useQuery({
    queryKey: keys.insights(10),
    queryFn: () => fetchPredictiveMaintenanceInsights(10),
  });

  if (isError) return <ErrorBlock message="Couldn't load insights." />;
  if (isLoading || !data) return <SkeletonBlock height="h-64" />;

  const riskChart = RISK_ORDER.map((k) => ({
    key: k,
    label: riskStyles[k].label,
    value: data.risk_tier_breakdown[k],
    tone: riskStyles[k].tone,
  }));

  const statusChart = STATUS_ORDER.map((k) => ({
    key: k,
    label: statusStyles[k].label,
    value: data.status_breakdown[k],
    tone: statusStyles[k].tone,
  }));

  const failureChart = FAILURE_ORDER.map((k) => ({
    key: k,
    label: failureStyles[k].label,
    value: data.failure_mode_breakdown[k],
    tone: failureStyles[k].tone,
  }));

  const sourceChart = SOURCE_ORDER.map((k) => ({
    key: k,
    label: sourceStyles[k].label,
    value: data.source_breakdown[k],
    tone: sourceStyles[k].tone,
  }));

  const agingChart: { key: string; label: string; value: number; tone: Tone }[] = [
    {
      key: "fresh",
      label: "Fresh",
      value: data.aging_breakdown.fresh,
      tone: "good",
    },
    {
      key: "mature",
      label: "Mature",
      value: data.aging_breakdown.mature,
      tone: "info",
    },
    {
      key: "stale",
      label: "Stale",
      value: data.aging_breakdown.stale,
      tone: "crit",
    },
  ];

  // For the failure-mode-impact horizontal bar — use whichever max is
  // larger to scale every bar.
  const modeImpactMax = data.failure_mode_impact.reduce(
    (acc, r) => Math.max(acc, r.total_estimated_repair_cost),
    0,
  );

  return (
    <div className="space-y-6">
      {/* Risk + Status breakdowns */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <BreakdownChart
          title="Risk tier"
          subtitle="Lifetime distribution across predictions."
          data={riskChart}
          unitLabel="predictions"
        />
        <BreakdownChart
          title="Status"
          subtitle="Where every prediction stands today."
          data={statusChart}
          unitLabel="predictions"
        />
      </section>

      {/* Failure mode + Source */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div>
          <h3 className="text-sm font-semibold">Failure mode</h3>
          <p className="mb-3 text-xs text-muted-foreground">
            Predictions grouped by component class.
          </p>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={failureChart}
                layout="vertical"
                margin={{ top: 4, right: 16, bottom: 4, left: 0 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="hsl(var(--border))"
                  horizontal={false}
                />
                <XAxis
                  type="number"
                  allowDecimals={false}
                  tick={{
                    fontSize: 11,
                    fill: "hsl(var(--muted-foreground))",
                  }}
                  stroke="hsl(var(--border))"
                />
                <YAxis
                  type="category"
                  dataKey="label"
                  width={100}
                  tick={{
                    fontSize: 11,
                    fill: "hsl(var(--muted-foreground))",
                  }}
                  stroke="hsl(var(--border))"
                />
                <RechartsTooltip
                  cursor={{ fill: "hsl(var(--muted))" }}
                  contentStyle={{
                    background: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  formatter={(v: number) => v.toLocaleString()}
                />
                <Bar dataKey="value" radius={[0, 6, 6, 0]}>
                  {failureChart.map((d) => (
                    <Cell key={d.key} fill={toneStyles[d.tone].fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <BreakdownChart
          title="Source split"
          subtitle="Calendar PMs vs. AI-derived failure predictions."
          data={sourceChart}
          unitLabel="predictions"
        />
      </section>

      {/* Aging + Failure mode impact $ */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <BreakdownChart
          title="Aging (open queue)"
          subtitle="How long open predictions have been sitting."
          data={agingChart}
          unitLabel="open"
        />
        <div>
          <h3 className="text-sm font-semibold">Open exposure by mode</h3>
          <p className="mb-3 text-xs text-muted-foreground">
            Sum of estimated repair $ across open predictions.
          </p>
          {data.failure_mode_impact.length === 0 ? (
            <p className="text-xs text-muted-foreground">No exposure data.</p>
          ) : (
            <div className="space-y-2">
              {data.failure_mode_impact.map((m) => {
                const fs = failureStyles[m.failure_mode];
                const ts = toneStyles[fs.tone];
                const pct =
                  modeImpactMax > 0
                    ? (m.total_estimated_repair_cost / modeImpactMax) * 100
                    : 0;
                return (
                  <div key={m.failure_mode} className="space-y-1">
                    <div className="flex items-center justify-between gap-3 text-xs">
                      <span className="inline-flex items-center gap-1.5 font-medium">
                        <fs.Icon className={cn("h-3.5 w-3.5", ts.text)} />
                        {fs.label}
                      </span>
                      <span className="font-mono tabular-nums">
                        {formatMoney(m.total_estimated_repair_cost)}{" "}
                        <span className="ml-1 text-muted-foreground">
                          {m.open_count} open
                        </span>
                      </span>
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full"
                        style={{
                          width: `${Math.min(100, pct)}%`,
                          background: ts.fill,
                        }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </section>

      {/* Top equipment by exposure + Top by individual exposure */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="mb-3 flex items-center gap-2">
            <Truck className="h-4 w-4 text-info" />
            <h4 className="text-sm font-semibold">Top equipment exposure</h4>
          </div>
          {data.top_equipment_exposure.length === 0 ? (
            <p className="text-xs text-muted-foreground">No data.</p>
          ) : (
            <div className="space-y-1.5">
              {data.top_equipment_exposure.slice(0, 8).map((e) => {
                const r = riskStyles[e.worst_risk_tier];
                const ts = toneStyles[r.tone];
                return (
                  <div
                    key={e.equipment_id}
                    className="flex items-center justify-between gap-3 text-xs"
                  >
                    <div className="min-w-0 flex-1">
                      <div
                        className="truncate font-medium"
                        title={e.equipment_label}
                      >
                        {e.equipment_label}
                      </div>
                      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                        <span className="font-mono">{e.equipment_id}</span>
                        <span>·</span>
                        <span>{e.open_count} open</span>
                        {e.total_estimated_downtime_hours > 0 && (
                          <>
                            <span>·</span>
                            <span>
                              {formatHours(e.total_estimated_downtime_hours)} hrs
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
                          ts.bg,
                          ts.text,
                        )}
                      >
                        {r.label}
                      </span>
                      <span className="font-mono text-xs tabular-nums">
                        {formatMoney(e.total_estimated_repair_cost)}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <div className="mb-3 flex items-center gap-2">
            <CircleDollarSign className="h-4 w-4 text-info" />
            <h4 className="text-sm font-semibold">Top by repair $</h4>
          </div>
          {data.top_by_exposure.length === 0 ? (
            <p className="text-xs text-muted-foreground">No data.</p>
          ) : (
            <div className="space-y-1.5">
              {data.top_by_exposure.slice(0, 8).map((p) => {
                const r = riskStyles[p.risk_tier];
                const f = failureStyles[p.failure_mode];
                return (
                  <div
                    key={p.id}
                    className="flex items-center justify-between gap-3 text-xs"
                  >
                    <div className="min-w-0 flex-1">
                      <div
                        className="truncate font-medium"
                        title={p.equipment_label}
                      >
                        {p.equipment_label}
                      </div>
                      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                        <f.Icon className="h-3 w-3" />
                        {f.label}
                        <span>·</span>
                        <span>
                          {p.days_until_due === null
                            ? "—"
                            : p.days_until_due < 0
                              ? `${Math.abs(p.days_until_due).toFixed(0)}d overdue`
                              : `${p.days_until_due.toFixed(0)}d`}
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
                          toneStyles[r.tone].bg,
                          toneStyles[r.tone].text,
                        )}
                      >
                        {r.label}
                      </span>
                      <span className="font-mono text-xs tabular-nums">
                        {p.estimated_repair_cost === null
                          ? "—"
                          : formatMoney(p.estimated_repair_cost)}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </section>

      {/* Recent completions */}
      <section className="rounded-lg border border-border bg-card p-4">
        <div className="mb-3 flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 text-primary" />
          <h4 className="text-sm font-semibold">Recent completions</h4>
        </div>
        {data.recent_completions.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No completions yet — clean queue.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
            {data.recent_completions.slice(0, 10).map((r) => {
              const f = failureStyles[r.failure_mode];
              const st = statusStyles[r.status];
              return (
                <div
                  key={r.id}
                  className="flex items-center justify-between gap-3 text-xs"
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium" title={r.equipment_label}>
                      {r.equipment_label}
                    </div>
                    <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                      <f.Icon className="h-3 w-3" />
                      {f.label}
                      <span>·</span>
                      <span>{formatDate(r.resolved_at)}</span>
                    </div>
                  </div>
                  <span
                    className={cn(
                      "rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                      toneStyles[st.tone].bg,
                      toneStyles[st.tone].text,
                    )}
                  >
                    {st.label}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

function BreakdownChart({
  title,
  subtitle,
  data,
  unitLabel,
}: {
  title: string;
  subtitle: string;
  data: { key: string; label: string; value: number; tone: Tone }[];
  unitLabel: string;
}) {
  const total = data.reduce((acc, d) => acc + d.value, 0);
  return (
    <div>
      <h3 className="text-sm font-semibold">{title}</h3>
      <p className="mb-3 text-xs text-muted-foreground">
        {subtitle} {total.toLocaleString()} {unitLabel}.
      </p>
      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
              stroke="hsl(var(--border))"
            />
            <YAxis
              allowDecimals={false}
              tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
              stroke="hsl(var(--border))"
            />
            <RechartsTooltip
              cursor={{ fill: "hsl(var(--muted))" }}
              contentStyle={{
                background: "hsl(var(--card))",
                border: "1px solid hsl(var(--border))",
                borderRadius: 8,
                fontSize: 12,
              }}
              formatter={(v: number) => v.toLocaleString()}
            />
            <Bar dataKey="value" radius={[6, 6, 0, 0]}>
              {data.map((d) => (
                <Cell key={d.key} fill={toneStyles[d.tone].fill} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Right rail: Recommendations (Phase 6 placeholder)
// ──────────────────────────────────────────────────────────────────────

function RecommendationsRail() {
  return (
    <Card className="lg:sticky lg:top-6">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" />
          <CardTitle>Maintenance plan</CardTitle>
        </div>
        <CardDescription>
          Drill into a prediction and Claude drafts a full repair plan.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="rounded-lg border border-dashed border-border bg-muted/30 p-4 text-center">
          <p className="text-sm font-medium">Coming in Phase 6</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Select a row and Claude will reconcile recent work-order
            history, propose a parts list and labor estimate, suggest
            a vendor, and offer a date window — directly in this panel.
          </p>
          <div className="mt-3 flex justify-center">
            <Wrench className="h-6 w-6 text-muted-foreground/50" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────

function ErrorBlock({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-critical/30 bg-critical/5 p-3 text-sm text-critical">
      <span className="inline-flex items-center gap-1.5">
        <AlertTriangle className="h-3.5 w-3.5" />
        {message}
      </span>
    </div>
  );
}

function SkeletonBlock({ height = "h-24" }: { height?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-muted", height)} />;
}

function SkeletonGrid({ count }: { count: number }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonBlock key={i} height="h-24" />
      ))}
    </div>
  );
}

// Short localized date for badges + history rows.
function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

// Compact USD: 1.2M / 850K / 1,200.
function formatMoney(n: number): string {
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) {
    return `${sign}$${(abs / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}M`;
  }
  if (abs >= 10_000) {
    return `${sign}$${(abs / 1_000).toFixed(0)}K`;
  }
  return `${sign}$${abs.toLocaleString(undefined, {
    maximumFractionDigits: 0,
  })}`;
}

// Hours: compact for big numbers, raw integer for small ones.
function formatHours(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1_000_000) {
    return `${(n / 1_000_000).toFixed(1)}M`;
  }
  if (abs >= 10_000) {
    return `${(n / 1_000).toFixed(0)}K`;
  }
  return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
}
