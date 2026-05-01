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
  Building2,
  Check,
  ChevronLeft,
  ChevronRight,
  HelpCircle,
  Sparkles,
  Timer,
  TrendingUp,
  Users,
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
  fetchTimecardInsights,
  fetchTimecardList,
  fetchTimecardSummary,
  type ListParams,
  type SortDir,
  type SortField,
  type TimecardListRow,
  type VarianceStatus,
} from "./timecards-api";

/**
 * Timecards module — Phase 5 page.
 *
 * Layout:
 *   ┌── 4 KPI tiles (FTE) ─────────────────────────────┐ ┌── Recommendations
 *   │  Total FTE · Variance · Overtime · Overhead      │ │   (right rail)
 *   ├── Tabs: Overview · List · Insights ──────────────┤ │
 *   │  Overview: variance mix bar + headcount totals   │ │
 *   │  List:     paginated TanStack table              │ │
 *   │  Insights: variance over/under, overtime, ratio  │ │
 *   └──────────────────────────────────────────────────┘ └──────────────────
 *
 * One entity per **job class**. Two analytical axes:
 *   - variance (under / on_track / over / unknown) — actual vs plan
 *   - overtime (last-month hours over the monthly target)
 *
 * Plus the **overhead ratio** — overhead-dept FTE / (overhead + direct).
 *
 * Severity → token mapping (no new colors):
 *   primary  = on_track / healthy ratio
 *   info     = neutral fact (counts, breakeven)
 *   warning  = caution (overstaffed, mild overtime, mid ratio)
 *   critical = alert (heavy overtime, big variance miss)
 *
 * Mutations: timecards endpoints are read-only. The query-key factory
 * is ready for Phase 6 (e.g. plan adjustments, OT approvals).
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

const varianceStyles: Record<
  VarianceStatus,
  { tone: Tone; label: string; Icon: typeof Check }
> = {
  on_track: { tone: "good", label: "On track", Icon: Check },
  over: { tone: "warn", label: "Over plan", Icon: ArrowUpRight },
  under: { tone: "crit", label: "Under plan", Icon: ArrowDownRight },
  unknown: { tone: "neutral", label: "Unknown", Icon: HelpCircle },
};

// Query key factory.
const keys = {
  all: ["timecards"] as const,
  summary: () => [...keys.all, "summary"] as const,
  list: (params: ListParams) => [...keys.all, "list", params] as const,
  insights: (topN: number) => [...keys.all, "insights", topN] as const,
};

// ──────────────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────────────

export function TimecardsPage() {
  return (
    <div className="p-6 lg:p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Timecards</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          FTE actuals vs. plan by job class, last-month overtime, and overhead
          ratio across the workforce.
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
    queryFn: fetchTimecardSummary,
  });

  // Four FTE-oriented tiles. Severity adapts:
  //   - Variance: |x|<=10 = good, |x|<=20 = warn, else crit
  //     (Backend returns variance_pct as percentage points, not a
  //      ratio, e.g. 12.5 = 12.5%.)
  //   - Overtime: classes_with_overtime: 0=good, share<20% warn, else crit
  //   - Overhead ratio: <30% good, ≤45% info, else warn
  const tiles = useMemo(() => {
    if (!data) return [];

    const vp = data.total_variance_pct;
    const varianceTone: Tone =
      vp == null
        ? "neutral"
        : Math.abs(vp) <= 10
          ? "good"
          : Math.abs(vp) <= 20
            ? "warn"
            : "crit";

    const otShare =
      data.total_classes > 0
        ? data.classes_with_overtime / data.total_classes
        : 0;
    const overtimeTone: Tone =
      data.classes_with_overtime === 0
        ? "good"
        : otShare < 0.2
          ? "warn"
          : "crit";

    const ratio = data.overhead_ratio_pct;
    const overheadTone: Tone =
      ratio == null
        ? "neutral"
        : ratio < 30
          ? "good"
          : ratio <= 45
            ? "info"
            : "warn";

    return [
      {
        key: "fte",
        tone: "info" as Tone,
        Icon: Users,
        value: formatFte(data.total_actual_fte),
        label: "Total FTE",
        sub: `${data.total_classes} classes · plan ${formatFte(data.total_projected_fte)}`,
      },
      {
        key: "variance",
        tone: varianceTone,
        Icon:
          vp == null
            ? HelpCircle
            : vp >= 0
              ? ArrowUpRight
              : ArrowDownRight,
        value: vp == null ? "—" : `${vp >= 0 ? "+" : ""}${vp.toFixed(1)}%`,
        label: "FTE variance",
        sub:
          vp == null
            ? "no plan data"
            : vp >= 0
              ? "actuals above plan"
              : "actuals below plan",
      },
      {
        key: "overtime",
        tone: overtimeTone,
        Icon: Timer,
        value: data.classes_with_overtime.toLocaleString(),
        label: "Overtime classes",
        sub:
          data.classes_with_overtime === 0
            ? "no classes over target"
            : `avg ${data.avg_overtime_pct.toFixed(1)}% over target`,
      },
      {
        key: "overhead",
        tone: overheadTone,
        Icon: Building2,
        value: ratio == null ? "—" : `${ratio.toFixed(1)}%`,
        label: "Overhead ratio",
        sub: `${data.total_overhead_departments} OH depts · ${data.total_job_types} job types`,
      },
    ];
  }, [data]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Workforce snapshot</CardTitle>
          <CardDescription>
            Rolling 12-month FTE actuals vs. plan · pulled from the
            FTE-class marts
          </CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          {data && (
            <>
              <Badge variant="mono">
                {formatFte(data.total_actual_fte)} actual
              </Badge>
              <Badge variant="mono">
                {formatFte(data.total_projected_fte)} planned
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
    queryFn: fetchTimecardSummary,
  });
  const insights = useQuery({
    queryKey: keys.insights(10),
    queryFn: () => fetchTimecardInsights(10),
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

  // Headline visualization: actual vs plan FTE side-by-side. The
  // backend gives us totals (and class-level top-N for over/under on
  // the Insights tab) — a categorical variance pie isn't computable
  // here without a full enumeration, so we lean into the totals.
  const headcountChart = [
    {
      label: "Actual",
      value: s.total_actual_fte,
      tone: "info" as Tone,
    },
    {
      label: "Plan",
      value: s.total_projected_fte,
      tone: "good" as Tone,
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
      <div className="md:col-span-2">
        <h3 className="text-sm font-semibold">Actual vs. plan FTE</h3>
        <p className="mb-3 text-xs text-muted-foreground">
          Total rolling 12-month headcount against the projected book
          (band: ±{ins.variance_band_pct.toFixed(0)}%).
        </p>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={headcountChart}
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
                allowDecimals
                tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                stroke="hsl(var(--border))"
                tickFormatter={(v: number) => v.toFixed(0)}
              />
              <RechartsTooltip
                cursor={{ fill: "hsl(var(--muted))" }}
                contentStyle={{
                  background: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                formatter={(v: number) => formatFte(v)}
              />
              <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                {headcountChart.map((d) => (
                  <Cell key={d.label} fill={toneStyles[d.tone].fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-semibold">Headcount</h3>
        <SummaryRow
          label="Actual FTE"
          value={formatFte(s.total_actual_fte)}
        />
        <SummaryRow
          label="Projected FTE"
          value={formatFte(s.total_projected_fte)}
        />
        <SummaryRow
          label="Variance"
          value={
            s.total_variance_pct == null
              ? "—"
              : `${s.total_variance_pct >= 0 ? "+" : ""}${s.total_variance_pct.toFixed(1)}%`
          }
          sub={
            s.total_actual_fte - s.total_projected_fte === 0
              ? undefined
              : `${(s.total_actual_fte - s.total_projected_fte).toFixed(1)} FTE`
          }
        />
        <div className="border-t border-border pt-3" />
        <h3 className="text-sm font-semibold">Overtime</h3>
        <SummaryRow
          label="Avg overtime"
          value={`${s.avg_overtime_pct.toFixed(1)}%`}
        />
        <SummaryRow
          label="Classes over target"
          value={s.classes_with_overtime.toLocaleString()}
          sub={
            s.total_classes > 0
              ? `${formatPercent(s.classes_with_overtime / s.total_classes)} of total`
              : undefined
          }
        />
        <div className="border-t border-border pt-3" />
        <h3 className="text-sm font-semibold">Composition</h3>
        <SummaryRow
          label="Job types"
          value={s.total_job_types.toLocaleString()}
        />
        <SummaryRow
          label="Overhead depts"
          value={s.total_overhead_departments.toLocaleString()}
          sub={
            s.overhead_ratio_pct == null
              ? undefined
              : `${s.overhead_ratio_pct.toFixed(1)}% ratio`
          }
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
  const [status, setStatus] = useState<VarianceStatus | "all">("all");
  const [overtimeFilter, setOvertimeFilter] = useState<"all" | "ot" | "no_ot">(
    "all",
  );
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [sorting, setSorting] = useState<SortingState>([
    { id: "variance_pct", desc: true },
  ]);

  const sortBy = (sorting[0]?.id ?? "variance_pct") as SortField;
  const sortDir: SortDir = sorting[0]?.desc ? "desc" : "asc";

  const params: ListParams = useMemo(
    () => ({
      page,
      page_size: pageSize,
      sort_by: sortBy,
      sort_dir: sortDir,
      ...(search.trim() ? { search: search.trim() } : {}),
      ...(status !== "all" ? { status } : {}),
      ...(overtimeFilter === "ot"
        ? { overtime_only: true }
        : overtimeFilter === "no_ot"
          ? { overtime_only: false }
          : {}),
    }),
    [page, pageSize, sortBy, sortDir, search, status, overtimeFilter],
  );

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: keys.list(params),
    queryFn: () => fetchTimecardList(params),
    placeholderData: keepPreviousData,
  });

  const columns = useMemo<ColumnDef<TimecardListRow>[]>(
    () => [
      {
        accessorKey: "class_name",
        header: "Class",
        cell: ({ row }) => (
          <div className="flex flex-col gap-0.5">
            <span className="font-medium">{row.original.class_name}</span>
            {(row.original.code || row.original.craft_class) && (
              <span className="text-[11px] text-muted-foreground">
                {[row.original.code, row.original.craft_class]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            )}
          </div>
        ),
      },
      {
        accessorKey: "actual_avg_fte",
        header: "Actual FTE",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums">
            {row.original.actual_avg_fte != null
              ? formatFte(row.original.actual_avg_fte)
              : "—"}
          </span>
        ),
      },
      {
        accessorKey: "projected_avg_fte",
        header: "Plan FTE",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums">
            {row.original.projected_avg_fte != null
              ? formatFte(row.original.projected_avg_fte)
              : "—"}
          </span>
        ),
      },
      {
        accessorKey: "variance_pct",
        header: "Variance",
        cell: ({ row }) => {
          const vp = row.original.variance_pct;
          const v = row.original.variance;
          const vs = varianceStyles[row.original.variance_status];
          const ts = toneStyles[vs.tone];
          if (vp == null) {
            return <span className="text-xs text-muted-foreground">—</span>;
          }
          return (
            <div className="flex flex-col gap-0.5">
              <span
                className={cn(
                  "inline-flex w-fit items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-[11px] font-medium tabular-nums",
                  ts.bg,
                  ts.text,
                )}
              >
                <vs.Icon className="h-3 w-3" />
                {vp >= 0 ? "+" : ""}
                {vp.toFixed(1)}%
              </span>
              {v != null && Math.abs(v) >= 0.05 && (
                <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                  {v >= 0 ? "+" : ""}
                  {v.toFixed(1)} FTE
                </span>
              )}
            </div>
          );
        },
      },
      {
        accessorKey: "monthly_hours",
        header: "Target hrs",
        cell: ({ row }) => (
          <span className="font-mono text-xs tabular-nums">
            {row.original.monthly_hours != null
              ? row.original.monthly_hours.toFixed(0)
              : "—"}
          </span>
        ),
      },
      {
        accessorKey: "last_month_actuals",
        header: "Last mo hrs",
        cell: ({ row }) => (
          <span className="font-mono text-xs tabular-nums">
            {row.original.last_month_actuals != null
              ? row.original.last_month_actuals.toFixed(0)
              : "—"}
          </span>
        ),
      },
      {
        accessorKey: "overtime_pct",
        header: "Overtime",
        cell: ({ row }) => {
          const otPct = row.original.overtime_pct;
          const otHrs = row.original.overtime_hours;
          if (otPct == null || otHrs == null) {
            return <span className="text-xs text-muted-foreground">—</span>;
          }
          if (otHrs <= 0) {
            return (
              <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
                <Check className="h-3 w-3" />
                none
              </span>
            );
          }
          // Tone for the OT pill: ≤10% warn, >10% crit.
          const tone: Tone = otPct <= 10 ? "warn" : "crit";
          const ts = toneStyles[tone];
          return (
            <div className="flex flex-col gap-0.5">
              <span
                className={cn(
                  "inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[11px] font-medium tabular-nums",
                  ts.bg,
                  ts.text,
                )}
              >
                <Timer className="h-3 w-3" />+{otPct.toFixed(1)}%
              </span>
              <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                +{otHrs.toFixed(0)} hrs
              </span>
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
          placeholder="Search class, code, craft…"
          className="w-full sm:w-72"
        />
        <Select<VarianceStatus | "all">
          value={status}
          onChange={(v) => {
            setStatus(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All variance" },
            { value: "on_track", label: "On track" },
            { value: "over", label: "Over plan" },
            { value: "under", label: "Under plan" },
            { value: "unknown", label: "Unknown" },
          ]}
        />
        <Select<"all" | "ot" | "no_ot">
          value={overtimeFilter}
          onChange={(v) => {
            setOvertimeFilter(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All overtime" },
            { value: "ot", label: "Has overtime" },
            { value: "no_ot", label: "No overtime" },
          ]}
        />
        {isFetching && (
          <span className="text-[11px] text-muted-foreground">refreshing…</span>
        )}
      </div>

      {isError && <ErrorBlock message="Couldn't load timecard list." />}

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
                  No job classes match the current filters.
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
    queryKey: keys.insights(10),
    queryFn: () => fetchTimecardInsights(10),
  });

  if (isError) return <ErrorBlock message="Couldn't load insights." />;
  if (isLoading || !data) return <SkeletonBlock height="h-64" />;

  // Build a horizontal-bar-friendly dataset for overtime leaders.
  const overtimeChart = data.overtime_leaders
    .filter((o) => o.overtime_pct != null && o.overtime_hours != null)
    .map((o) => ({
      class_name: truncate(o.class_name, 24),
      overtime_pct: o.overtime_pct ?? 0,
    }));

  return (
    <div className="space-y-6">
      {/* Variance over/under tables */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <VarianceTable
          title="Overstaffed classes"
          icon={<ArrowUpRight className="h-4 w-4 text-warning" />}
          rows={data.variance_over}
          tone="warn"
        />
        <VarianceTable
          title="Understaffed classes"
          icon={<ArrowDownRight className="h-4 w-4 text-critical" />}
          rows={data.variance_under}
          tone="crit"
        />
      </section>

      {/* Overtime leaders chart + overhead ratio */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <h3 className="mb-2 text-sm font-semibold">Overtime leaders</h3>
          <p className="mb-3 text-xs text-muted-foreground">
            Top classes by % over the monthly hour target.
          </p>
          {overtimeChart.length === 0 ? (
            <p className="text-xs text-muted-foreground">No overtime found.</p>
          ) : (
            <div
              className="w-full"
              style={{
                height: `${Math.max(96, overtimeChart.length * 32 + 32)}px`,
              }}
            >
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={overtimeChart}
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
                    tickFormatter={(v: number) => `${v.toFixed(0)}%`}
                  />
                  <YAxis
                    type="category"
                    dataKey="class_name"
                    width={160}
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
                    formatter={(v: number) => `${v.toFixed(1)}%`}
                  />
                  <Bar
                    dataKey="overtime_pct"
                    radius={[0, 6, 6, 0]}
                    fill={toneStyles.warn.fill}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <div className="mb-3 flex items-center gap-2">
            <Building2 className="h-4 w-4 text-info" />
            <h4 className="text-sm font-semibold">Overhead ratio</h4>
          </div>
          <Stat
            label="Overhead FTE"
            value={formatFte(data.overhead_ratio.overhead_fte)}
            tone="info"
          />
          <Stat
            label="Direct FTE"
            value={formatFte(data.overhead_ratio.direct_fte)}
            tone="good"
          />
          <Stat
            label="Total FTE"
            value={formatFte(
              data.overhead_ratio.overhead_fte + data.overhead_ratio.direct_fte,
            )}
          />
          <div className="my-3 border-t border-border" />
          <Stat
            label="Ratio"
            value={
              data.overhead_ratio.ratio_pct == null
                ? "—"
                : `${data.overhead_ratio.ratio_pct.toFixed(1)}%`
            }
            tone={
              data.overhead_ratio.ratio_pct == null
                ? "neutral"
                : data.overhead_ratio.ratio_pct < 30
                  ? "good"
                  : data.overhead_ratio.ratio_pct <= 45
                    ? "info"
                    : "warn"
            }
          />
          <p className="mt-3 text-[11px] text-muted-foreground">
            Overhead share of total FTE. &lt;30% is healthy for a
            heavy-civil contractor; &gt;45% suggests trimming
            non-billable headcount.
          </p>
        </div>
      </section>

      {/* Overtime detail table */}
      {data.overtime_leaders.length > 0 && (
        <section className="rounded-lg border border-border bg-card p-4">
          <div className="mb-3 flex items-center gap-2">
            <Timer className="h-4 w-4 text-warning" />
            <h4 className="text-sm font-semibold">Overtime detail</h4>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th className="py-2 font-medium">Class</th>
                  <th className="py-2 text-right font-medium">Target hrs</th>
                  <th className="py-2 text-right font-medium">Last mo hrs</th>
                  <th className="py-2 text-right font-medium">Overtime hrs</th>
                  <th className="py-2 text-right font-medium">Overtime %</th>
                </tr>
              </thead>
              <tbody>
                {data.overtime_leaders.map((o) => (
                  <tr key={o.class_name} className="border-b border-border/50">
                    <td className="py-2 font-medium">{o.class_name}</td>
                    <td className="py-2 text-right font-mono tabular-nums">
                      {o.monthly_hours != null
                        ? o.monthly_hours.toFixed(0)
                        : "—"}
                    </td>
                    <td className="py-2 text-right font-mono tabular-nums">
                      {o.last_month_actuals != null
                        ? o.last_month_actuals.toFixed(0)
                        : "—"}
                    </td>
                    <td className="py-2 text-right font-mono tabular-nums text-warning">
                      {o.overtime_hours != null
                        ? `+${o.overtime_hours.toFixed(0)}`
                        : "—"}
                    </td>
                    <td className="py-2 text-right font-mono tabular-nums text-warning">
                      {o.overtime_pct != null
                        ? `+${o.overtime_pct.toFixed(1)}%`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <div className="text-[11px] text-muted-foreground">
        As of {formatDateTime(data.as_of)} · variance band: ±
        {data.variance_band_pct.toFixed(1)}%
      </div>
    </div>
  );
}

function VarianceTable({
  title,
  icon,
  rows,
  tone,
}: {
  title: string;
  icon: React.ReactNode;
  rows: Array<{
    class_name: string;
    actual_avg_fte: number | null;
    projected_avg_fte: number | null;
    variance: number | null;
    variance_pct: number | null;
  }>;
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
          {rows.slice(0, 6).map((r) => (
            <div
              key={r.class_name}
              className="flex items-center justify-between gap-3 text-xs"
            >
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium" title={r.class_name}>
                  {r.class_name}
                </div>
                <div className="font-mono text-[11px] text-muted-foreground tabular-nums">
                  {r.actual_avg_fte != null ? formatFte(r.actual_avg_fte) : "—"}{" "}
                  /{" "}
                  {r.projected_avg_fte != null
                    ? formatFte(r.projected_avg_fte)
                    : "—"}
                </div>
              </div>
              <div className={cn("text-right font-mono tabular-nums", ts.text)}>
                <div>
                  {r.variance_pct != null
                    ? `${r.variance_pct >= 0 ? "+" : ""}${r.variance_pct.toFixed(1)}%`
                    : "—"}
                </div>
                <div className="text-[11px] opacity-80">
                  {r.variance != null
                    ? `${r.variance >= 0 ? "+" : ""}${r.variance.toFixed(1)} FTE`
                    : ""}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
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
          AI-generated next actions for workforce planning.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="rounded-lg border border-dashed border-border bg-muted/30 p-4 text-center">
          <p className="text-sm font-medium">Coming in Phase 6</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Claude will flag overtime classes for hiring asks, surface
            understaffed crews against upcoming job starts, and
            recommend overhead trims when the ratio drifts above plan
            — directly in this panel.
          </p>
          <div className="mt-3 flex justify-center">
            <TrendingUp className="h-6 w-6 text-muted-foreground/50" />
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

function formatFte(n: number): string {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
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

function truncate(s: string, max: number): string {
  return s.length <= max ? s : s.slice(0, max - 1) + "…";
}
