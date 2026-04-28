import { useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import {
  AlertTriangle,
  ArrowDown,
  ArrowDownRight,
  ArrowUp,
  ArrowUpDown,
  ArrowUpRight,
  Briefcase,
  CalendarClock,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  Clock,
  HelpCircle,
  Receipt,
  Sparkles,
  Target,
  TrendingDown,
  TrendingUp,
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
  fetchJobInsights,
  fetchJobList,
  fetchJobSummary,
  type BillingStatus,
  type FinancialStatus,
  type JobListRow,
  type ListParams,
  type ScheduleStatus,
  type SortDir,
  type SortField,
} from "./jobs-api";

/**
 * Jobs module — Phase 5 page.
 *
 * Layout:
 *   ┌── 4 KPI tiles (P&L) ─────────────────────────────┐ ┌── Recommendations
 *   │  Active · Schedule risk · Margin · Loss-making   │ │   (right rail)
 *   ├── Tabs: Overview · List · Insights ──────────────┤ │
 *   │  Overview: schedule mix bar + WIP totals         │ │
 *   │  List:     paginated TanStack table (P&L cols)   │ │
 *   │  Insights: sched/fin/bill bars, est-accuracy,    │ │
 *   │            top profit/loss/over/under            │ │
 *   └──────────────────────────────────────────────────┘ └──────────────────
 *
 * Three orthogonal status axes — schedule (on_schedule / at_risk / late /
 * no_schedule / unknown), financial (profitable / breakeven / loss /
 * unknown), billing (balanced / over_billed / under_billed / unknown).
 * Severity → token mapping is consistent: primary = healthy, info =
 * neutral, warning = caution, critical = alert.
 *
 * Mutations: jobs endpoints are read-only. The Phase 5 brief calls for
 * "TanStack Query mutations with optimistic updates where safe" but
 * there's no write surface yet. The query-key factory below keeps
 * things ready for Phase 6 (e.g. priority re-ordering, schedule edits)
 * — invalidate on `keys.list(...)` after a useMutation success and the
 * table snaps back.
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

const scheduleStyles: Record<
  ScheduleStatus,
  { tone: Tone; label: string; Icon: typeof Check }
> = {
  on_schedule: { tone: "good", label: "On schedule", Icon: Check },
  at_risk: { tone: "warn", label: "At risk", Icon: Clock },
  late: { tone: "crit", label: "Late", Icon: AlertTriangle },
  no_schedule: { tone: "neutral", label: "No schedule", Icon: CalendarClock },
  unknown: { tone: "neutral", label: "Unknown", Icon: HelpCircle },
};

const financialStyles: Record<
  FinancialStatus,
  { tone: Tone; label: string; Icon: typeof Check }
> = {
  profitable: { tone: "good", label: "Profitable", Icon: TrendingUp },
  breakeven: { tone: "info", label: "Breakeven", Icon: Target },
  loss: { tone: "crit", label: "Loss", Icon: TrendingDown },
  unknown: { tone: "neutral", label: "Unknown", Icon: HelpCircle },
};

const billingStyles: Record<
  BillingStatus,
  { tone: Tone; label: string; Icon: typeof Check }
> = {
  balanced: { tone: "good", label: "Balanced", Icon: Check },
  over_billed: { tone: "warn", label: "Over-billed", Icon: ArrowUpRight },
  under_billed: { tone: "info", label: "Under-billed", Icon: ArrowDownRight },
  unknown: { tone: "neutral", label: "Unknown", Icon: HelpCircle },
};

const SCHEDULE_ORDER: ScheduleStatus[] = [
  "on_schedule",
  "at_risk",
  "late",
  "no_schedule",
  "unknown",
];

const FINANCIAL_ORDER: FinancialStatus[] = [
  "profitable",
  "breakeven",
  "loss",
  "unknown",
];

// Query key factory — invalidations stay consistent across hooks /
// future write mutations.
const keys = {
  all: ["jobs"] as const,
  summary: () => [...keys.all, "summary"] as const,
  list: (params: ListParams) => [...keys.all, "list", params] as const,
  insights: (topN: number) => [...keys.all, "insights", topN] as const,
};

// ──────────────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────────────

export function JobsPage() {
  return (
    <div className="p-6 lg:p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Jobs</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Active contracts across schedule, financial, and billing axes —
          P&amp;L, projected end, and over/under-billing exposure.
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
    queryFn: fetchJobSummary,
  });

  // Four P&L-oriented tiles. Severity adapts:
  //   - Schedule risk: 0 = good, <10% of total = warn, else crit
  //   - Margin: positive = good (above breakeven band), near-zero = info,
  //     negative = crit. The backend's breakeven_band lives in the
  //     insights endpoint, but for tile severity we use a simple ±2%
  //     heuristic that matches the default DEFAULT_BREAKEVEN_BAND_PCT.
  //   - Loss-making count: 0 = good, <10% of total = warn, else crit
  const tiles = useMemo(() => {
    if (!data) return [];
    const total = data.total_jobs || 0;
    const scheduleRisk = data.jobs_at_risk + data.jobs_late;
    const scheduleRiskShare = total > 0 ? scheduleRisk / total : 0;

    const scheduleTone: Tone =
      scheduleRisk === 0 ? "good" : scheduleRiskShare < 0.1 ? "warn" : "crit";

    // weighted_avg_margin_pct is *already* a percent (e.g. 12.5), not a
    // ratio — see backend service. Tile classification:
    //   > 2  → profitable (good)
    //   ±2  → breakeven (info)
    //   < -2 → loss (crit)
    const margin = data.weighted_avg_margin_pct;
    const marginTone: Tone =
      margin == null
        ? "neutral"
        : margin > 2
          ? "good"
          : margin >= -2
            ? "info"
            : "crit";

    const lossShare = total > 0 ? data.jobs_loss / total : 0;
    const lossTone: Tone =
      data.jobs_loss === 0 ? "good" : lossShare < 0.1 ? "warn" : "crit";

    return [
      {
        key: "active",
        tone: "info" as Tone,
        Icon: Briefcase,
        value: total.toLocaleString(),
        label: "Active jobs",
        sub: `${data.jobs_with_wip} with WIP · ${data.jobs_scheduled} scheduled`,
      },
      {
        key: "schedule",
        tone: scheduleTone,
        Icon: Clock,
        value: scheduleRisk.toLocaleString(),
        label: "Schedule risk",
        sub: `${data.jobs_at_risk} at risk · ${data.jobs_late} late`,
      },
      {
        key: "margin",
        tone: marginTone,
        Icon: margin != null && margin < 0 ? TrendingDown : TrendingUp,
        value: margin == null ? "—" : `${margin.toFixed(1)}%`,
        label: "Weighted margin",
        sub:
          data.total_revenue_earned > 0
            ? `${formatCurrency(data.total_gross_profit_td)} GP · ${formatCurrency(data.total_revenue_earned)} earned`
            : "no revenue earned yet",
      },
      {
        key: "loss",
        tone: lossTone,
        Icon: TrendingDown,
        value: data.jobs_loss.toLocaleString(),
        label: "Loss-making",
        sub: `${data.jobs_profitable} profitable · ${data.jobs_breakeven} breakeven`,
      },
    ];
  }, [data]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Pipeline health</CardTitle>
          <CardDescription>
            All active contracts · pulled from the WIP + schedule marts
          </CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          {data && (
            <>
              <Badge variant="mono">
                {formatCurrency(data.total_contract_value)} contract
              </Badge>
              <Badge variant="mono">
                {formatPercent(data.avg_percent_complete)} avg complete
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
  const { data, isLoading, isError } = useQuery({
    queryKey: keys.summary(),
    queryFn: fetchJobSummary,
  });

  if (isError) return <ErrorBlock message="Couldn't load overview." />;
  if (isLoading || !data) return <SkeletonBlock height="h-64" />;

  // Schedule chart only shows the three actionable buckets (the
  // unknown/no_schedule pair is noise on Overview but we surface it on
  // Insights for completeness).
  const scheduleChart = [
    {
      status: "on_schedule" as const,
      count: data.jobs_on_schedule,
    },
    { status: "at_risk" as const, count: data.jobs_at_risk },
    { status: "late" as const, count: data.jobs_late },
  ];

  const total = data.total_jobs || 0;

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
      <div className="md:col-span-2">
        <h3 className="text-sm font-semibold">Schedule mix</h3>
        <p className="mb-3 text-xs text-muted-foreground">
          Active jobs by where they stand against projected end date.
        </p>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={scheduleChart}
              margin={{ top: 8, right: 8, bottom: 8, left: 0 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="hsl(var(--border))"
              />
              <XAxis
                dataKey="status"
                tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                tickFormatter={(s: ScheduleStatus) => scheduleStyles[s].label}
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
                labelFormatter={(s: ScheduleStatus) => scheduleStyles[s].label}
              />
              <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                {scheduleChart.map((d) => (
                  <Cell
                    key={d.status}
                    fill={toneStyles[scheduleStyles[d.status].tone].fill}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-semibold">WIP totals</h3>
        <SummaryRow
          label="Contract value"
          value={formatCurrency(data.total_contract_value)}
        />
        <SummaryRow
          label="Cost to date"
          value={formatCurrency(data.total_cost_to_date)}
          sub={
            data.total_contract_value > 0
              ? formatPercent(
                  data.total_cost_to_date / data.total_contract_value,
                )
              : undefined
          }
        />
        <SummaryRow
          label="Revenue earned"
          value={formatCurrency(data.total_revenue_earned)}
        />
        <SummaryRow
          label="Gross profit · TD"
          value={formatCurrency(data.total_gross_profit_td)}
        />
        <div className="border-t border-border pt-3" />
        <h3 className="text-sm font-semibold">Job mix</h3>
        <SummaryRow
          label="Profitable"
          value={data.jobs_profitable.toLocaleString()}
          sub={formatPercent(safeShare(data.jobs_profitable, total))}
        />
        <SummaryRow
          label="Breakeven"
          value={data.jobs_breakeven.toLocaleString()}
          sub={formatPercent(safeShare(data.jobs_breakeven, total))}
        />
        <SummaryRow
          label="Loss"
          value={data.jobs_loss.toLocaleString()}
          sub={formatPercent(safeShare(data.jobs_loss, total))}
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

// ── List ─────────────────────────────────────────────────────────────

function ListTab() {
  const [search, setSearch] = useState("");
  const [scheduleStatus, setScheduleStatus] = useState<
    ScheduleStatus | "all"
  >("all");
  const [financialStatus, setFinancialStatus] = useState<
    FinancialStatus | "all"
  >("all");
  const [billingStatus, setBillingStatus] = useState<BillingStatus | "all">(
    "all",
  );
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [sorting, setSorting] = useState<SortingState>([
    { id: "priority", desc: false },
  ]);

  const sortBy = (sorting[0]?.id ?? "priority") as SortField;
  const sortDir: SortDir = sorting[0]?.desc ? "desc" : "asc";

  const params: ListParams = useMemo(
    () => ({
      page,
      page_size: pageSize,
      sort_by: sortBy,
      sort_dir: sortDir,
      ...(search.trim() ? { search: search.trim() } : {}),
      ...(scheduleStatus !== "all"
        ? { schedule_status: scheduleStatus }
        : {}),
      ...(financialStatus !== "all"
        ? { financial_status: financialStatus }
        : {}),
      ...(billingStatus !== "all" ? { billing_status: billingStatus } : {}),
    }),
    [
      page,
      pageSize,
      sortBy,
      sortDir,
      search,
      scheduleStatus,
      financialStatus,
      billingStatus,
    ],
  );

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: keys.list(params),
    queryFn: () => fetchJobList(params),
    placeholderData: keepPreviousData,
  });

  const columns = useMemo<ColumnDef<JobListRow>[]>(
    () => [
      {
        accessorKey: "priority",
        header: "P",
        cell: ({ row }) =>
          row.original.priority != null ? (
            <span className="font-mono text-xs tabular-nums">
              {row.original.priority}
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">—</span>
          ),
      },
      {
        accessorKey: "job",
        header: "Job",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-medium">{row.original.job}</span>
        ),
      },
      {
        accessorKey: "schedule_days_to_end",
        header: "Schedule",
        cell: ({ row }) => {
          const s = scheduleStyles[row.original.schedule_status];
          const ts = toneStyles[s.tone];
          const days = row.original.schedule_days_to_end;
          return (
            <div className="flex flex-col gap-0.5">
              <span
                className={cn(
                  "inline-flex w-fit items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium",
                  ts.bg,
                  ts.text,
                )}
              >
                <s.Icon className="h-3 w-3" />
                {s.label}
              </span>
              {days != null && (
                <span className="text-[11px] text-muted-foreground">
                  {days >= 0 ? `${days}d to end` : `${Math.abs(days)}d past`}
                </span>
              )}
            </div>
          );
        },
      },
      {
        accessorKey: "percent_complete",
        header: "% Complete",
        cell: ({ row }) => {
          const pct = row.original.percent_complete;
          if (pct == null)
            return <span className="text-xs text-muted-foreground">—</span>;
          // Bar uses the same neutral muted bg + accent fill pattern as
          // the Performance card on the home dashboard.
          const clamped = Math.max(0, Math.min(1, pct));
          return (
            <div className="flex items-center gap-2">
              <div className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full bg-accent"
                  style={{ width: `${clamped * 100}%` }}
                />
              </div>
              <span className="font-mono text-xs tabular-nums">
                {formatPercent(pct)}
              </span>
            </div>
          );
        },
      },
      {
        accessorKey: "total_contract",
        header: "Contract",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums">
            {row.original.total_contract != null
              ? formatCurrency(row.original.total_contract)
              : "—"}
          </span>
        ),
      },
      {
        accessorKey: "est_gross_profit_pct",
        header: "Margin %",
        cell: ({ row }) => {
          const pct = row.original.est_gross_profit_pct;
          const fs = financialStyles[row.original.financial_status];
          const ts = toneStyles[fs.tone];
          if (pct == null) {
            return (
              <span className="text-xs text-muted-foreground">—</span>
            );
          }
          // Backend stores fractional ratio (0.20 = 20%). Show as %.
          return (
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[11px] font-medium tabular-nums",
                ts.bg,
                ts.text,
              )}
            >
              <fs.Icon className="h-3 w-3" />
              {(pct * 100).toFixed(1)}%
            </span>
          );
        },
      },
      {
        accessorKey: "over_under_billings",
        header: "Billing",
        cell: ({ row }) => {
          const bs = billingStyles[row.original.billing_status];
          const ts = toneStyles[bs.tone];
          const v = row.original.over_under_billings;
          return (
            <div className="flex flex-col gap-0.5">
              <span
                className={cn(
                  "inline-flex w-fit items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium",
                  ts.bg,
                  ts.text,
                )}
              >
                <bs.Icon className="h-3 w-3" />
                {bs.label}
              </span>
              {v != null && Math.abs(v) > 0 && (
                <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                  {v > 0 ? "+" : ""}
                  {formatCurrency(v)}
                </span>
              )}
            </div>
          );
        },
      },
    ],
    [],
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
          placeholder="Search job description…"
          className="w-full sm:w-72"
        />
        <Select<ScheduleStatus | "all">
          value={scheduleStatus}
          onChange={(v) => {
            setScheduleStatus(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All schedules" },
            { value: "on_schedule", label: "On schedule" },
            { value: "at_risk", label: "At risk" },
            { value: "late", label: "Late" },
            { value: "no_schedule", label: "No schedule" },
            { value: "unknown", label: "Unknown" },
          ]}
        />
        <Select<FinancialStatus | "all">
          value={financialStatus}
          onChange={(v) => {
            setFinancialStatus(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All margins" },
            { value: "profitable", label: "Profitable" },
            { value: "breakeven", label: "Breakeven" },
            { value: "loss", label: "Loss" },
            { value: "unknown", label: "Unknown" },
          ]}
        />
        <Select<BillingStatus | "all">
          value={billingStatus}
          onChange={(v) => {
            setBillingStatus(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All billing" },
            { value: "balanced", label: "Balanced" },
            { value: "over_billed", label: "Over-billed" },
            { value: "under_billed", label: "Under-billed" },
            { value: "unknown", label: "Unknown" },
          ]}
        />
        {isFetching && (
          <span className="text-[11px] text-muted-foreground">refreshing…</span>
        )}
      </div>

      {isError && <ErrorBlock message="Couldn't load job list." />}

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
                  No jobs match the current filters.
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

// Lightweight token-styled select. Hand-rolled — four filter dropdowns
// don't justify pulling in @radix-ui/react-select.
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

// ── Insights ─────────────────────────────────────────────────────────

function InsightsTab() {
  const { data, isLoading, isError } = useQuery({
    queryKey: keys.insights(10),
    queryFn: () => fetchJobInsights(10),
  });

  if (isError) return <ErrorBlock message="Couldn't load insights." />;
  if (isLoading || !data) return <SkeletonBlock height="h-64" />;

  const scheduleData = SCHEDULE_ORDER.map((s) => ({
    status: s,
    count: data.schedule_breakdown[s],
  }));
  const financialData = FINANCIAL_ORDER.map((s) => ({
    status: s,
    count: data.financial_breakdown[s],
  }));

  return (
    <div className="space-y-6">
      {/* Schedule + Financial side-by-side */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Schedule breakdown</h3>
          <p className="mb-3 text-xs text-muted-foreground">
            All five buckets, including unscheduled tail.
          </p>
          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={scheduleData}
                margin={{ top: 4, right: 8, bottom: 4, left: 0 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="hsl(var(--border))"
                />
                <XAxis
                  dataKey="status"
                  tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                  tickFormatter={(s: ScheduleStatus) => scheduleStyles[s].label}
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
                  labelFormatter={(s: ScheduleStatus) =>
                    scheduleStyles[s].label
                  }
                />
                <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                  {scheduleData.map((d) => (
                    <Cell
                      key={d.status}
                      fill={toneStyles[scheduleStyles[d.status].tone].fill}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div>
          <h3 className="mb-2 text-sm font-semibold">Financial breakdown</h3>
          <p className="mb-3 text-xs text-muted-foreground">
            Margin classification across the WIP-eligible set.
          </p>
          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={financialData}
                margin={{ top: 4, right: 8, bottom: 4, left: 0 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="hsl(var(--border))"
                />
                <XAxis
                  dataKey="status"
                  tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                  tickFormatter={(s: FinancialStatus) =>
                    financialStyles[s].label
                  }
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
                  labelFormatter={(s: FinancialStatus) =>
                    financialStyles[s].label
                  }
                />
                <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                  {financialData.map((d) => (
                    <Cell
                      key={d.status}
                      fill={toneStyles[financialStyles[d.status].tone].fill}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </section>

      {/* Billing + Estimate accuracy */}
      <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="mb-3 flex items-center gap-2">
            <Receipt className="h-4 w-4 text-info" />
            <h4 className="text-sm font-semibold">Billing exposure</h4>
          </div>
          <Stat
            label="Over-billed"
            value={`${data.billing_metrics.over_billed_count} jobs · ${formatCurrency(data.billing_metrics.total_over_billed)}`}
            tone="warn"
          />
          <Stat
            label="Balanced"
            value={`${data.billing_metrics.balanced_count} jobs`}
            tone="good"
          />
          <Stat
            label="Under-billed"
            value={`${data.billing_metrics.under_billed_count} jobs · ${formatCurrency(data.billing_metrics.total_under_billed)}`}
            tone="info"
          />
          <Stat
            label="Unknown"
            value={`${data.billing_metrics.unknown_count} jobs`}
            tone="neutral"
          />
          <p className="mt-3 text-[11px] text-muted-foreground">
            Tolerance: ±{data.billing_balance_pct.toFixed(1)}% of contract
            classifies as balanced.
          </p>
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <div className="mb-3 flex items-center gap-2">
            <Target className="h-4 w-4 text-primary" />
            <h4 className="text-sm font-semibold">Estimate accuracy</h4>
          </div>
          <Stat
            label="Samples"
            value={data.estimate_accuracy.samples.toLocaleString()}
          />
          <Stat
            label="Jobs tracked"
            value={data.estimate_accuracy.jobs_tracked.toLocaleString()}
          />
          <Stat
            label="Avg variance"
            value={
              data.estimate_accuracy.avg_variance_pct == null
                ? "—"
                : `${data.estimate_accuracy.avg_variance_pct.toFixed(1)}%`
            }
            tone={
              data.estimate_accuracy.avg_variance_pct == null
                ? "neutral"
                : data.estimate_accuracy.avg_variance_pct >= 0
                  ? "good"
                  : "warn"
            }
          />
          <Stat
            label="Avg |variance|"
            value={
              data.estimate_accuracy.avg_abs_variance_pct == null
                ? "—"
                : `${data.estimate_accuracy.avg_abs_variance_pct.toFixed(1)}%`
            }
          />
          <p className="mt-3 text-[11px] text-muted-foreground">
            Positive avg variance = actuals running under estimate (money
            left over). |Avg| measures absolute accuracy.
          </p>
        </div>
      </section>

      {/* Top profit / loss / billing tables */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <MoneyTable
          title="Top profit"
          icon={<TrendingUp className="h-4 w-4 text-primary" />}
          rows={data.top_profit}
          tone="good"
        />
        <MoneyTable
          title="Top loss"
          icon={<TrendingDown className="h-4 w-4 text-critical" />}
          rows={data.top_loss}
          tone="crit"
        />
        <MoneyTable
          title="Top over-billed"
          icon={<ArrowUpRight className="h-4 w-4 text-warning" />}
          rows={data.top_over_billed}
          tone="warn"
        />
        <MoneyTable
          title="Top under-billed"
          icon={<ArrowDownRight className="h-4 w-4 text-info" />}
          rows={data.top_under_billed}
          tone="info"
        />
      </section>

      <div className="text-[11px] text-muted-foreground">
        As of {formatDateTime(data.as_of)} · at-risk window:{" "}
        {data.at_risk_days}d · breakeven band: ±
        {data.breakeven_band_pct.toFixed(1)}%
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: Tone;
}) {
  const ts = toneStyles[tone];
  return (
    <div className="flex items-center justify-between gap-3 py-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span
        className={cn(
          "font-mono text-sm font-semibold tabular-nums",
          tone !== "neutral" && ts.text,
        )}
      >
        {value}
      </span>
    </div>
  );
}

function MoneyTable({
  title,
  icon,
  rows,
  tone,
}: {
  title: string;
  icon: React.ReactNode;
  rows: { id: string; job: string; value: number; percent_complete: number | null }[];
  tone: Tone;
}) {
  const ts = toneStyles[tone];
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center gap-2">
        {icon}
        <h4 className="text-sm font-semibold">{title}</h4>
      </div>
      {rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">No data.</p>
      ) : (
        <div className="space-y-1.5">
          {rows.slice(0, 5).map((r) => (
            <div
              key={r.id}
              className="flex items-center justify-between gap-3 text-xs"
            >
              <span className="truncate font-medium" title={r.job}>
                {r.job}
              </span>
              <span
                className={cn(
                  "font-mono tabular-nums",
                  ts.text,
                )}
              >
                {formatCurrency(r.value)}
              </span>
            </div>
          ))}
        </div>
      )}
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
          <CardTitle>Recommendations</CardTitle>
        </div>
        <CardDescription>
          AI-generated next actions for your active book of work.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="rounded-lg border border-dashed border-border bg-muted/30 p-4 text-center">
          <p className="text-sm font-medium">Coming in Phase 6</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Claude will rank schedule slips by recovery cost, surface
            change-order candidates from over-billed jobs, and flag fade
            risk on near-complete jobs — directly in this panel.
          </p>
          <div className="mt-3 flex justify-center">
            <CircleDollarSign className="h-6 w-6 text-muted-foreground/50" />
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
      {message}
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

function safeShare(part: number, total: number): number {
  return total > 0 ? part / total : 0;
}

function formatCurrency(n: number): string {
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

function formatPercent(n: number): string {
  return `${(n * 100).toFixed(0)}%`;
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}
