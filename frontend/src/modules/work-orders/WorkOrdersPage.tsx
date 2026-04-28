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
  ArrowUp,
  ArrowUpDown,
  CalendarClock,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  Clock,
  HelpCircle,
  PauseCircle,
  Sparkles,
  Wrench,
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
  fetchWorkOrderInsights,
  fetchWorkOrderList,
  fetchWorkOrderSummary,
  type ListParams,
  type SortDir,
  type SortField,
  type WorkOrderListRow,
  type WorkOrderPriority,
  type WorkOrderStatus,
} from "./work-orders-api";

/**
 * Work Orders module — Phase 5 page.
 *
 * Layout:
 *   ┌── 4 KPI tiles (shop $) ──────────────────────────┐ ┌── Recommendations
 *   │  Open · Overdue · Avg age · Cost vs budget       │ │   (right rail)
 *   ├── Tabs: Overview · List · Insights ──────────────┤ │
 *   │  Overview: status mix bar + shop totals          │ │
 *   │  List:     paginated TanStack table              │ │
 *   │  Insights: status mix · cost vs budget panel     │ │
 *   └──────────────────────────────────────────────────┘ └──────────────────
 *
 * Two analytical axes per WO:
 *   - status   (open / closed / hold / unknown)
 *   - priority (critical / high / normal / unknown)
 * Plus the **overdue** boolean — open WOs older than the threshold
 * (default 30 days, configurable on every endpoint).
 *
 * Severity → token mapping (no new colors):
 *   primary  = closed / on-budget
 *   info     = open · normal priority · neutral fact
 *   warning  = hold · high priority · mid age
 *   critical = overdue · critical priority · over budget
 *
 * Mutations: work-orders endpoints are read-only. The query-key factory
 * is ready for Phase 6 (e.g. status flips, mechanic assignment).
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

const statusStyles: Record<
  WorkOrderStatus,
  { tone: Tone; label: string; Icon: typeof Check }
> = {
  open: { tone: "info", label: "Open", Icon: Wrench },
  closed: { tone: "good", label: "Closed", Icon: Check },
  hold: { tone: "warn", label: "On hold", Icon: PauseCircle },
  unknown: { tone: "neutral", label: "Unknown", Icon: HelpCircle },
};

const priorityStyles: Record<
  WorkOrderPriority,
  { tone: Tone; label: string; Icon: typeof Check }
> = {
  critical: { tone: "crit", label: "Critical", Icon: Zap },
  high: { tone: "warn", label: "High", Icon: AlertTriangle },
  normal: { tone: "info", label: "Normal", Icon: Wrench },
  unknown: { tone: "neutral", label: "Unknown", Icon: HelpCircle },
};

const STATUS_ORDER: WorkOrderStatus[] = [
  "open",
  "closed",
  "hold",
  "unknown",
];

// Query key factory.
const keys = {
  all: ["work-orders"] as const,
  summary: () => [...keys.all, "summary"] as const,
  list: (params: ListParams) => [...keys.all, "list", params] as const,
  insights: () => [...keys.all, "insights"] as const,
};

// ──────────────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────────────

export function WorkOrdersPage() {
  return (
    <div className="p-6 lg:p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Work Orders</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Equipment shop activity — open backlog, overdue tail, cost vs.
          budget across the maintenance program.
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
    queryFn: fetchWorkOrderSummary,
  });

  // Four shop-floor tiles. Severity adapts:
  //   - Overdue: 0=good, share<10%=warn, else crit
  //   - Avg age: <7d=good, <30d=info, <90d=warn, else crit
  //   - Cost vs budget: variance≤0=good, ≤10% over=info, ≤25%=warn, else crit
  const tiles = useMemo(() => {
    if (!data) return [];

    const overdueShare =
      data.open_count > 0 ? data.overdue_count / data.open_count : 0;
    const overdueTone: Tone =
      data.overdue_count === 0
        ? "good"
        : overdueShare < 0.1
          ? "warn"
          : "crit";

    const age = data.avg_age_days_open;
    const ageTone: Tone =
      age < 7 ? "good" : age < 30 ? "info" : age < 90 ? "warn" : "crit";

    // Cost variance: budget can be 0 if nothing has been estimated.
    const variance = data.total_cost_to_date - data.total_budget;
    const variancePct =
      data.total_budget > 0 ? (variance / data.total_budget) * 100 : null;
    const costTone: Tone =
      data.total_budget === 0
        ? "neutral"
        : variance <= 0
          ? "good"
          : variancePct! <= 10
            ? "info"
            : variancePct! <= 25
              ? "warn"
              : "crit";

    return [
      {
        key: "open",
        tone: "info" as Tone,
        Icon: Wrench,
        value: data.open_count.toLocaleString(),
        label: "Open WOs",
        sub: `${data.closed_count.toLocaleString()} closed · ${data.hold_count.toLocaleString()} on hold`,
      },
      {
        key: "overdue",
        tone: overdueTone,
        Icon: AlertTriangle,
        value: data.overdue_count.toLocaleString(),
        label: "Overdue",
        sub: `> ${data.overdue_threshold_days}d open${data.open_count > 0 ? ` · ${formatPercent(overdueShare)} of open` : ""}`,
      },
      {
        key: "age",
        tone: ageTone,
        Icon: Clock,
        value: `${age.toFixed(1)}d`,
        label: "Avg age (open)",
        sub:
          data.open_count > 0
            ? "rolling across open backlog"
            : "no open WOs",
      },
      {
        key: "cost",
        tone: costTone,
        Icon: CircleDollarSign,
        value:
          variancePct == null
            ? formatCurrency(data.total_cost_to_date)
            : `${variancePct >= 0 ? "+" : ""}${variancePct.toFixed(1)}%`,
        label: variancePct == null ? "Spend (no budget)" : "Cost vs budget",
        sub:
          data.total_budget > 0
            ? `${formatCurrency(data.total_cost_to_date)} / ${formatCurrency(data.total_budget)}`
            : "no budgeted WOs",
      },
    ];
  }, [data]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Shop snapshot</CardTitle>
          <CardDescription>
            All WOs from the equipment maintenance program · Vista
            ``emwo`` table normalized
          </CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          {data && (
            <>
              <Badge variant="mono">
                {data.total_work_orders.toLocaleString()} WOs
              </Badge>
              <Badge variant="mono">
                {formatCurrency(data.total_cost_to_date)} spent
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
    queryFn: fetchWorkOrderSummary,
  });
  const insights = useQuery({
    queryKey: keys.insights(),
    queryFn: fetchWorkOrderInsights,
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
  const ins = insights.data;

  // Status mix uses insights.status_counts (authoritative bucketing).
  const statusChart = STATUS_ORDER.map((st) => ({
    status: st,
    count: ins.status_counts[st],
  }));

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
      <div className="md:col-span-2">
        <h3 className="text-sm font-semibold">Status mix</h3>
        <p className="mb-3 text-xs text-muted-foreground">
          All WOs by lifecycle bucket. Open is the active backlog;
          closed is historical.
        </p>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={statusChart}
              margin={{ top: 8, right: 8, bottom: 8, left: 0 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="hsl(var(--border))"
              />
              <XAxis
                dataKey="status"
                tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                tickFormatter={(s: WorkOrderStatus) => statusStyles[s].label}
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
                labelFormatter={(s: WorkOrderStatus) =>
                  statusStyles[s].label
                }
              />
              <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                {statusChart.map((d) => (
                  <Cell
                    key={d.status}
                    fill={toneStyles[statusStyles[d.status].tone].fill}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-semibold">Backlog</h3>
        <SummaryRow
          label="Open"
          value={s.open_count.toLocaleString()}
          sub={
            s.total_work_orders > 0
              ? formatPercent(s.open_count / s.total_work_orders)
              : undefined
          }
        />
        <SummaryRow
          label="On hold"
          value={s.hold_count.toLocaleString()}
        />
        <SummaryRow
          label="Closed"
          value={s.closed_count.toLocaleString()}
        />
        <div className="border-t border-border pt-3" />
        <h3 className="text-sm font-semibold">Aging</h3>
        <SummaryRow
          label="Overdue"
          value={s.overdue_count.toLocaleString()}
          sub={`> ${s.overdue_threshold_days}d`}
        />
        <SummaryRow
          label="Avg age (open)"
          value={`${s.avg_age_days_open.toFixed(1)}d`}
        />
        <div className="border-t border-border pt-3" />
        <h3 className="text-sm font-semibold">Cost</h3>
        <SummaryRow
          label="Spend"
          value={formatCurrency(s.total_cost_to_date)}
        />
        <SummaryRow
          label="Budget"
          value={formatCurrency(s.total_budget)}
        />
        {s.total_budget > 0 && (
          <SummaryRow
            label="Variance"
            value={formatCurrency(s.total_cost_to_date - s.total_budget)}
            sub={`${(((s.total_cost_to_date - s.total_budget) / s.total_budget) * 100).toFixed(1)}%`}
          />
        )}
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
  const [status, setStatus] = useState<WorkOrderStatus | "all">("all");
  const [priority, setPriority] = useState<WorkOrderPriority | "all">("all");
  const [overdueFilter, setOverdueFilter] = useState<
    "all" | "overdue" | "on_time"
  >("all");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [sorting, setSorting] = useState<SortingState>([
    { id: "open_date", desc: true },
  ]);

  const sortBy = (sorting[0]?.id ?? "open_date") as SortField;
  const sortDir: SortDir = sorting[0]?.desc ? "desc" : "asc";

  const params: ListParams = useMemo(
    () => ({
      page,
      page_size: pageSize,
      sort_by: sortBy,
      sort_dir: sortDir,
      ...(search.trim() ? { search: search.trim() } : {}),
      ...(status !== "all" ? { status } : {}),
      ...(priority !== "all" ? { priority } : {}),
      ...(overdueFilter === "overdue"
        ? { overdue: true }
        : overdueFilter === "on_time"
          ? { overdue: false }
          : {}),
    }),
    [page, pageSize, sortBy, sortDir, search, status, priority, overdueFilter],
  );

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: keys.list(params),
    queryFn: () => fetchWorkOrderList(params),
    placeholderData: keepPreviousData,
  });

  const columns = useMemo<ColumnDef<WorkOrderListRow>[]>(
    () => [
      {
        accessorKey: "work_order",
        header: "WO",
        cell: ({ row }) => (
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-sm font-medium">
              {row.original.work_order}
            </span>
            {row.original.equipment && (
              <span
                className="truncate text-[11px] text-muted-foreground"
                title={row.original.equipment}
              >
                {row.original.equipment}
              </span>
            )}
          </div>
        ),
      },
      {
        accessorKey: "description",
        header: "Description",
        enableSorting: false,
        cell: ({ row }) => (
          <span
            className="line-clamp-2 text-xs"
            title={row.original.description ?? undefined}
          >
            {row.original.description ?? (
              <span className="text-muted-foreground">—</span>
            )}
          </span>
        ),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => {
          const ss = statusStyles[row.original.status];
          const ts = toneStyles[ss.tone];
          return (
            <span
              className={cn(
                "inline-flex w-fit items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium",
                ts.bg,
                ts.text,
              )}
            >
              <ss.Icon className="h-3 w-3" />
              {ss.label}
            </span>
          );
        },
      },
      {
        accessorKey: "priority",
        header: "Priority",
        cell: ({ row }) => {
          const ps = priorityStyles[row.original.priority];
          const ts = toneStyles[ps.tone];
          return (
            <span
              className={cn(
                "inline-flex w-fit items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium",
                ts.bg,
                ts.text,
              )}
            >
              <ps.Icon className="h-3 w-3" />
              {ps.label}
            </span>
          );
        },
      },
      {
        accessorKey: "age_days",
        header: "Age",
        cell: ({ row }) => {
          const age = row.original.age_days;
          const overdue = row.original.overdue;
          if (age == null)
            return <span className="text-xs text-muted-foreground">—</span>;
          // Closed WOs render age as a neutral "lifespan", open WOs
          // get severity tones based on age + overdue flag.
          const isOpen = row.original.status === "open";
          const tone: Tone = !isOpen
            ? "neutral"
            : overdue
              ? "crit"
              : age >= 14
                ? "warn"
                : "info";
          const ts = toneStyles[tone];
          return (
            <span
              className={cn(
                "inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[11px] font-medium tabular-nums",
                ts.bg,
                ts.text,
              )}
            >
              {overdue && isOpen && <AlertTriangle className="h-3 w-3" />}
              {age}d
            </span>
          );
        },
      },
      {
        accessorKey: "open_date",
        header: "Opened",
        cell: ({ row }) => (
          <span className="font-mono text-xs tabular-nums">
            {row.original.open_date ? formatDate(row.original.open_date) : "—"}
          </span>
        ),
      },
      {
        accessorKey: "total_cost",
        header: "Cost",
        cell: ({ row }) => {
          const cost = row.original.total_cost;
          const est = row.original.estimated_cost;
          if (cost == null && est == null) {
            return <span className="text-xs text-muted-foreground">—</span>;
          }
          const variance =
            cost != null && est != null && est > 0
              ? ((cost - est) / est) * 100
              : null;
          const tone: Tone =
            variance == null
              ? "neutral"
              : variance <= 0
                ? "good"
                : variance <= 10
                  ? "info"
                  : variance <= 25
                    ? "warn"
                    : "crit";
          const ts = toneStyles[tone];
          return (
            <div className="flex flex-col gap-0.5">
              <span className="font-mono tabular-nums">
                {cost != null ? formatCurrency(cost) : "—"}
              </span>
              {variance != null && (
                <span
                  className={cn(
                    "inline-flex w-fit items-center rounded-full px-1.5 py-0 font-mono text-[10px] font-medium tabular-nums",
                    ts.bg,
                    ts.text,
                  )}
                >
                  {variance >= 0 ? "+" : ""}
                  {variance.toFixed(0)}%
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
          placeholder="Search WO, equipment, mechanic, job…"
          className="w-full sm:w-72"
        />
        <Select<WorkOrderStatus | "all">
          value={status}
          onChange={(v) => {
            setStatus(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All statuses" },
            { value: "open", label: "Open" },
            { value: "closed", label: "Closed" },
            { value: "hold", label: "On hold" },
            { value: "unknown", label: "Unknown" },
          ]}
        />
        <Select<WorkOrderPriority | "all">
          value={priority}
          onChange={(v) => {
            setPriority(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All priorities" },
            { value: "critical", label: "Critical" },
            { value: "high", label: "High" },
            { value: "normal", label: "Normal" },
            { value: "unknown", label: "Unknown" },
          ]}
        />
        <Select<"all" | "overdue" | "on_time">
          value={overdueFilter}
          onChange={(v) => {
            setOverdueFilter(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All ages" },
            { value: "overdue", label: "Overdue only" },
            { value: "on_time", label: "Within threshold" },
          ]}
        />
        {isFetching && (
          <span className="text-[11px] text-muted-foreground">refreshing…</span>
        )}
      </div>

      {isError && <ErrorBlock message="Couldn't load work-order list." />}

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
                  No work orders match the current filters.
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

// ── Insights ─────────────────────────────────────────────────────────

function InsightsTab() {
  const { data, isLoading, isError } = useQuery({
    queryKey: keys.insights(),
    queryFn: fetchWorkOrderInsights,
  });

  if (isError) return <ErrorBlock message="Couldn't load insights." />;
  if (isLoading || !data) return <SkeletonBlock height="h-64" />;

  const statusChart = STATUS_ORDER.map((st) => ({
    status: st,
    count: data.status_counts[st],
  }));

  const cvb = data.cost_vs_budget;
  const variancePct = cvb.variance_pct;
  const costTone: Tone =
    cvb.budget === 0
      ? "neutral"
      : cvb.variance <= 0
        ? "good"
        : variancePct! <= 10
          ? "info"
          : variancePct! <= 25
            ? "warn"
            : "crit";

  return (
    <div className="space-y-6">
      {/* Status mix + headline aging */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <h3 className="mb-2 text-sm font-semibold">Status breakdown</h3>
          <p className="mb-3 text-xs text-muted-foreground">
            All four buckets, including the unknown tail (malformed
            Vista status codes).
          </p>
          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={statusChart}
                margin={{ top: 4, right: 8, bottom: 4, left: 0 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="hsl(var(--border))"
                />
                <XAxis
                  dataKey="status"
                  tick={{
                    fontSize: 11,
                    fill: "hsl(var(--muted-foreground))",
                  }}
                  tickFormatter={(s: WorkOrderStatus) => statusStyles[s].label}
                  stroke="hsl(var(--border))"
                />
                <YAxis
                  allowDecimals={false}
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
                  labelFormatter={(s: WorkOrderStatus) =>
                    statusStyles[s].label
                  }
                />
                <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                  {statusChart.map((d) => (
                    <Cell
                      key={d.status}
                      fill={toneStyles[statusStyles[d.status].tone].fill}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <div className="mb-3 flex items-center gap-2">
            <CalendarClock className="h-4 w-4 text-info" />
            <h4 className="text-sm font-semibold">Aging</h4>
          </div>
          <Stat
            label="Avg age (open)"
            value={`${data.avg_age_days_open.toFixed(1)}d`}
            tone={
              data.avg_age_days_open < 7
                ? "good"
                : data.avg_age_days_open < 30
                  ? "info"
                  : data.avg_age_days_open < 90
                    ? "warn"
                    : "crit"
            }
          />
          <Stat
            label="Overdue"
            value={data.overdue_count.toLocaleString()}
            tone={data.overdue_count === 0 ? "good" : "crit"}
          />
          <Stat
            label="Threshold"
            value={`${data.overdue_threshold_days}d`}
          />
          <p className="mt-3 text-[11px] text-muted-foreground">
            Open WOs older than the threshold count as overdue. Tune
            via the ``overdue_days`` query param.
          </p>
        </div>
      </section>

      {/* Cost vs budget */}
      <section className="rounded-lg border border-border bg-card p-4">
        <div className="mb-3 flex items-center gap-2">
          <CircleDollarSign className="h-4 w-4 text-primary" />
          <h4 className="text-sm font-semibold">Cost vs. budget</h4>
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <Stat label="Cost to date" value={formatCurrency(cvb.cost_to_date)} />
            <Stat label="Budget" value={formatCurrency(cvb.budget)} />
            <div className="my-3 border-t border-border" />
            <Stat
              label="Variance"
              value={
                cvb.variance >= 0
                  ? `+${formatCurrency(cvb.variance)}`
                  : `−${formatCurrency(Math.abs(cvb.variance))}`
              }
              tone={costTone}
            />
            <Stat
              label="Variance %"
              value={
                variancePct == null
                  ? "—"
                  : `${variancePct >= 0 ? "+" : ""}${variancePct.toFixed(1)}%`
              }
              tone={costTone}
            />
          </div>
          <div>
            {cvb.budget > 0 ? (
              <div className="h-40 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={[
                      {
                        label: "Budget",
                        value: cvb.budget,
                        tone: "info" as Tone,
                      },
                      {
                        label: "Cost",
                        value: cvb.cost_to_date,
                        tone: costTone,
                      },
                    ]}
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
                      tick={{
                        fontSize: 11,
                        fill: "hsl(var(--muted-foreground))",
                      }}
                      stroke="hsl(var(--border))"
                      tickFormatter={(v: number) => formatCurrency(v)}
                    />
                    <YAxis
                      type="category"
                      dataKey="label"
                      width={70}
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
                      formatter={(v: number) => formatCurrency(v)}
                    />
                    <Bar dataKey="value" radius={[0, 6, 6, 0]}>
                      <Cell fill={toneStyles.info.fill} />
                      <Cell fill={toneStyles[costTone].fill} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                No budgeted WOs — variance unavailable.
              </p>
            )}
          </div>
        </div>
      </section>

      <div className="text-[11px] text-muted-foreground">
        As of {formatDateTime(data.as_of)} · overdue threshold:{" "}
        {data.overdue_threshold_days}d
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
          AI-generated next actions for the shop.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="rounded-lg border border-dashed border-border bg-muted/30 p-4 text-center">
          <p className="text-sm font-medium">Coming in Phase 6</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Claude will rank overdue WOs by equipment criticality,
            flag cost overruns against budgeted scopes, and suggest
            mechanic re-assignments when backlog skews — directly in
            this panel.
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

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString();
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}
