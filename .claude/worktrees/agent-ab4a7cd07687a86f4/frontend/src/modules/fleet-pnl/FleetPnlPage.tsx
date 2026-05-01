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
  Activity,
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  Clock,
  Fuel,
  HelpCircle,
  Receipt,
  Sparkles,
  Truck,
  Users,
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
  fetchFleetInsights,
  fetchFleetList,
  fetchFleetSummary,
  type InvoiceBucket,
  type LessorFlag,
  type ListParams,
  type SortDir,
  type SortField,
  type TruckListRow,
  type UtilizationBucket,
} from "./fleet-pnl-api";

/**
 * Fleet P&L module — Phase 5 page.
 *
 * Layout:
 *   ┌── 4 KPI tiles (fleet $) ─────────────────────────┐ ┌── Recommendations
 *   │  Trucks · Revenue · Uninvoiced · Rental cost     │ │   (right rail)
 *   ├── Tabs: Overview · List · Insights ──────────────┤ │
 *   │  Overview: utilization mix bar + breadth totals  │ │
 *   │  List:     paginated truck table                 │ │
 *   │  Insights: util/invoice bars, rental-in card,    │ │
 *   │            top rev/uninvoiced/underused/vendors  │ │
 *   └──────────────────────────────────────────────────┘ └──────────────────
 *
 * Three orthogonal classifications per truck:
 *   - utilization (idle / underutilized / healthy / heavily_utilized)
 *   - invoicing  (fully / partially / uninvoiced / unknown)
 *   - ownership  (owned / lessor / mixed / unknown)
 *
 * Severity → token mapping (no new colors):
 *   primary  = healthy / fully invoiced / owned baseline
 *   info     = neutral fact (counts, breadth, partial)
 *   warning  = caution (underutilized, uninvoiced share, mixed)
 *   critical = alert (idle trucks, large uninvoiced $)
 *
 * Mutations: fleet_pnl endpoints are read-only. The query-key factory
 * stays ready for Phase 6 (e.g. invoice push, rental return, truck
 * retire) — invalidate `keys.list(...)` after a useMutation success.
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

const utilizationStyles: Record<
  UtilizationBucket,
  { tone: Tone; label: string; Icon: typeof Check }
> = {
  healthy: { tone: "good", label: "Healthy", Icon: Check },
  underutilized: { tone: "warn", label: "Underused", Icon: Clock },
  heavily_utilized: { tone: "info", label: "Heavy use", Icon: Zap },
  idle: { tone: "crit", label: "Idle", Icon: AlertTriangle },
};

const invoiceStyles: Record<
  InvoiceBucket,
  { tone: Tone; label: string; Icon: typeof Check }
> = {
  fully_invoiced: { tone: "good", label: "Fully invoiced", Icon: Check },
  partially_invoiced: {
    tone: "info",
    label: "Partial",
    Icon: Receipt,
  },
  uninvoiced: { tone: "crit", label: "Uninvoiced", Icon: AlertTriangle },
  unknown: { tone: "neutral", label: "Unknown", Icon: HelpCircle },
};

const ownershipStyles: Record<
  LessorFlag,
  { tone: Tone; label: string; Icon: typeof Check }
> = {
  owned: { tone: "good", label: "Owned", Icon: Truck },
  lessor: { tone: "info", label: "Lessor", Icon: Users },
  mixed: { tone: "warn", label: "Mixed", Icon: HelpCircle },
  unknown: { tone: "neutral", label: "Unknown", Icon: HelpCircle },
};

const UTILIZATION_ORDER: UtilizationBucket[] = [
  "healthy",
  "heavily_utilized",
  "underutilized",
  "idle",
];

const INVOICE_ORDER: InvoiceBucket[] = [
  "fully_invoiced",
  "partially_invoiced",
  "uninvoiced",
  "unknown",
];

// Query key factory — keeps invalidations consistent across hooks /
// future write mutations.
const keys = {
  all: ["fleet-pnl"] as const,
  summary: () => [...keys.all, "summary"] as const,
  list: (params: ListParams) => [...keys.all, "list", params] as const,
  insights: (topN: number) => [...keys.all, "insights", topN] as const,
};

// ──────────────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────────────

export function FleetPnlPage() {
  return (
    <div className="p-6 lg:p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Fleet P&amp;L</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Per-truck haul activity — revenue, A/R exposure, ownership mix, and
          rental-in cost across the fleet.
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
    queryFn: fetchFleetSummary,
  });

  // Four tiles: trucks, revenue, uninvoiced AR, rental cost.
  // Severity adapts on the AR tile — uninvoiced share of total revenue
  // determines tone (≤5% good, ≤20% warn, else crit) so the operator
  // sees an at-a-glance "is the billing crew keeping up?".
  const tiles = useMemo(() => {
    if (!data) return [];

    const uninvoicedShare =
      data.total_revenue > 0
        ? data.uninvoiced_revenue / data.total_revenue
        : 0;
    const arTone: Tone =
      data.uninvoiced_revenue <= 0
        ? "good"
        : uninvoicedShare <= 0.05
          ? "good"
          : uninvoicedShare <= 0.2
            ? "warn"
            : "crit";

    // Invoice-rate is informational on the revenue tile.
    const invoiceRate = data.invoice_rate;

    return [
      {
        key: "trucks",
        tone: "info" as Tone,
        Icon: Truck,
        value: data.total_trucks.toLocaleString(),
        label: "Trucks active",
        sub: `${data.owned_trucks} owned · ${data.lessor_trucks} lessor${data.mixed_trucks ? ` · ${data.mixed_trucks} mixed` : ""}`,
      },
      {
        key: "revenue",
        tone: data.total_revenue > 0 ? ("good" as Tone) : ("neutral" as Tone),
        Icon: CircleDollarSign,
        value: formatCurrency(data.total_revenue),
        label: "Total revenue",
        sub:
          invoiceRate != null
            ? `${data.total_tickets.toLocaleString()} tickets · ${formatPercent(invoiceRate)} invoiced`
            : `${data.total_tickets.toLocaleString()} tickets`,
      },
      {
        key: "uninvoiced",
        tone: arTone,
        Icon: Receipt,
        value: formatCurrency(data.uninvoiced_revenue),
        label: "Uninvoiced A/R",
        sub:
          data.total_revenue > 0
            ? `${formatPercent(uninvoicedShare)} of haul revenue`
            : "no haul revenue yet",
      },
      {
        key: "rental",
        tone: "info" as Tone,
        Icon: Fuel,
        value: formatCurrency(data.rental_monthly_cost),
        label: "Rental-in / mo",
        sub: `${data.rental_contracts} contract${data.rental_contracts === 1 ? "" : "s"}`,
      },
    ];
  }, [data]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Fleet snapshot</CardTitle>
          <CardDescription>
            Haul-ticket rollup across owned + rented trucks · pulled from the
            equipment-utilization mart
          </CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          {data && (
            <>
              <Badge variant="mono">
                {data.unique_jobs.toLocaleString()} jobs
              </Badge>
              <Badge variant="mono">
                {data.unique_vendors.toLocaleString()} vendors
              </Badge>
              <Badge variant="mono">
                {data.unique_drivers.toLocaleString()} drivers
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
    queryFn: fetchFleetSummary,
  });
  const insights = useQuery({
    queryKey: keys.insights(10),
    queryFn: () => fetchFleetInsights(10),
  });

  if (summary.isError || insights.isError) {
    return <ErrorBlock message="Couldn't load overview." />;
  }
  if (summary.isLoading || insights.isLoading || !summary.data || !insights.data) {
    return <SkeletonBlock height="h-64" />;
  }

  const s = summary.data;
  const ins = insights.data;

  // Utilization chart on Overview shows all four buckets so the
  // operator can see "are we over-running healthy capacity?". Idle is
  // the alarm bucket.
  const utilizationChart = UTILIZATION_ORDER.map((b) => ({
    bucket: b,
    count: ins.utilization_breakdown[b],
  }));

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
      <div className="md:col-span-2">
        <h3 className="text-sm font-semibold">Utilization mix</h3>
        <p className="mb-3 text-xs text-muted-foreground">
          Trucks bucketed by ticket volume. Thresholds: ≤
          {ins.underutilized_max_tickets} = underused, ≥
          {ins.heavily_utilized_min_tickets} = heavy.
        </p>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={utilizationChart}
              margin={{ top: 8, right: 8, bottom: 8, left: 0 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="hsl(var(--border))"
              />
              <XAxis
                dataKey="bucket"
                tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                tickFormatter={(b: UtilizationBucket) =>
                  utilizationStyles[b].label
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
                labelFormatter={(b: UtilizationBucket) =>
                  utilizationStyles[b].label
                }
              />
              <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                {utilizationChart.map((d) => (
                  <Cell
                    key={d.bucket}
                    fill={toneStyles[utilizationStyles[d.bucket].tone].fill}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-semibold">Volume</h3>
        <SummaryRow
          label="Tickets"
          value={s.total_tickets.toLocaleString()}
          sub={s.active_days != null ? `${s.active_days}d active` : undefined}
        />
        <SummaryRow label="Total qty" value={formatNumber(s.total_qty)} />
        <SummaryRow
          label="Revenue"
          value={formatCurrency(s.total_revenue)}
        />
        <div className="border-t border-border pt-3" />
        <h3 className="text-sm font-semibold">A/R health</h3>
        <SummaryRow
          label="Invoiced"
          value={formatCurrency(s.invoiced_revenue)}
          sub={s.invoice_rate != null ? formatPercent(s.invoice_rate) : undefined}
        />
        <SummaryRow
          label="Uninvoiced"
          value={formatCurrency(s.uninvoiced_revenue)}
          sub={
            s.total_revenue > 0
              ? formatPercent(s.uninvoiced_revenue / s.total_revenue)
              : undefined
          }
        />
        <div className="border-t border-border pt-3" />
        <h3 className="text-sm font-semibold">Breadth</h3>
        <SummaryRow
          label="Jobs served"
          value={s.unique_jobs.toLocaleString()}
        />
        <SummaryRow
          label="Vendors"
          value={s.unique_vendors.toLocaleString()}
        />
        <SummaryRow
          label="Drivers"
          value={s.unique_drivers.toLocaleString()}
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
  const [lessorFlag, setLessorFlag] = useState<LessorFlag | "all">("all");
  const [invoiceBucket, setInvoiceBucket] = useState<InvoiceBucket | "all">(
    "all",
  );
  const [utilizationBucket, setUtilizationBucket] = useState<
    UtilizationBucket | "all"
  >("all");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [sorting, setSorting] = useState<SortingState>([
    { id: "revenue", desc: true },
  ]);

  const sortBy = (sorting[0]?.id ?? "revenue") as SortField;
  const sortDir: SortDir = sorting[0]?.desc ? "desc" : "asc";

  const params: ListParams = useMemo(
    () => ({
      page,
      page_size: pageSize,
      sort_by: sortBy,
      sort_dir: sortDir,
      ...(search.trim() ? { search: search.trim() } : {}),
      ...(lessorFlag !== "all" ? { lessor_flag: lessorFlag } : {}),
      ...(invoiceBucket !== "all" ? { invoice_bucket: invoiceBucket } : {}),
      ...(utilizationBucket !== "all"
        ? { utilization_bucket: utilizationBucket }
        : {}),
    }),
    [page, pageSize, sortBy, sortDir, search, lessorFlag, invoiceBucket, utilizationBucket],
  );

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: keys.list(params),
    queryFn: () => fetchFleetList(params),
    placeholderData: keepPreviousData,
  });

  const columns = useMemo<ColumnDef<TruckListRow>[]>(
    () => [
      {
        accessorKey: "truck",
        header: "Truck",
        cell: ({ row }) => {
          const o = ownershipStyles[row.original.lessor_flag];
          const ts = toneStyles[o.tone];
          return (
            <div className="flex flex-col gap-0.5">
              <span className="font-medium font-mono text-sm">
                {row.original.truck}
              </span>
              <span
                className={cn(
                  "inline-flex w-fit items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                  ts.bg,
                  ts.text,
                )}
              >
                <o.Icon className="h-2.5 w-2.5" />
                {o.label}
              </span>
            </div>
          );
        },
      },
      {
        accessorKey: "ticket_count",
        header: "Tickets",
        cell: ({ row }) => {
          const u = utilizationStyles[row.original.utilization_bucket];
          const ts = toneStyles[u.tone];
          return (
            <div className="flex flex-col gap-0.5">
              <span className="font-mono text-sm tabular-nums">
                {row.original.ticket_count.toLocaleString()}
              </span>
              <span
                className={cn(
                  "inline-flex w-fit items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                  ts.bg,
                  ts.text,
                )}
              >
                <u.Icon className="h-2.5 w-2.5" />
                {u.label}
              </span>
            </div>
          );
        },
      },
      {
        accessorKey: "revenue",
        header: "Revenue",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums">
            {formatCurrency(row.original.revenue)}
          </span>
        ),
      },
      {
        accessorKey: "uninvoiced_revenue",
        header: "Uninvoiced",
        cell: ({ row }) => {
          const ib = invoiceStyles[row.original.invoice_bucket];
          const ts = toneStyles[ib.tone];
          const v = row.original.uninvoiced_revenue;
          return (
            <div className="flex flex-col gap-0.5">
              <span
                className={cn(
                  "font-mono tabular-nums",
                  v > 0 && row.original.invoice_bucket === "uninvoiced"
                    ? "text-critical"
                    : "",
                )}
              >
                {formatCurrency(v)}
              </span>
              <span
                className={cn(
                  "inline-flex w-fit items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                  ts.bg,
                  ts.text,
                )}
              >
                <ib.Icon className="h-2.5 w-2.5" />
                {ib.label}
              </span>
            </div>
          );
        },
      },
      {
        accessorKey: "invoice_rate",
        header: "Inv %",
        cell: ({ row }) => {
          const r = row.original.invoice_rate;
          if (r == null)
            return <span className="text-xs text-muted-foreground">—</span>;
          // Reuse the progress-bar pattern from Jobs % Complete.
          const clamped = Math.max(0, Math.min(1, r));
          return (
            <div className="flex items-center gap-2">
              <div className="h-1.5 w-12 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full bg-primary"
                  style={{ width: `${clamped * 100}%` }}
                />
              </div>
              <span className="font-mono text-xs tabular-nums">
                {formatPercent(r)}
              </span>
            </div>
          );
        },
      },
      {
        accessorKey: "jobs_served",
        header: "Breadth",
        cell: ({ row }) => (
          <div className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
            <span>
              <span className="font-mono tabular-nums text-foreground">
                {row.original.jobs_served}
              </span>{" "}
              jobs
            </span>
            <span>
              <span className="font-mono tabular-nums text-foreground">
                {row.original.vendors_served}
              </span>{" "}
              vendors
            </span>
          </div>
        ),
      },
      {
        accessorKey: "last_ticket",
        header: "Last seen",
        cell: ({ row }) => {
          const d = row.original.last_ticket;
          if (!d) return <span className="text-xs text-muted-foreground">—</span>;
          return (
            <div className="flex flex-col gap-0.5 text-[11px]">
              <span className="font-mono tabular-nums">{formatDate(d)}</span>
              {row.original.active_days != null && (
                <span className="text-muted-foreground">
                  {row.original.active_days}d window
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
          placeholder="Search truck, vendor, material, driver…"
          className="w-full sm:w-72"
        />
        <Select<UtilizationBucket | "all">
          value={utilizationBucket}
          onChange={(v) => {
            setUtilizationBucket(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All utilization" },
            { value: "healthy", label: "Healthy" },
            { value: "heavily_utilized", label: "Heavy use" },
            { value: "underutilized", label: "Underused" },
            { value: "idle", label: "Idle" },
          ]}
        />
        <Select<InvoiceBucket | "all">
          value={invoiceBucket}
          onChange={(v) => {
            setInvoiceBucket(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All invoicing" },
            { value: "fully_invoiced", label: "Fully invoiced" },
            { value: "partially_invoiced", label: "Partial" },
            { value: "uninvoiced", label: "Uninvoiced" },
            { value: "unknown", label: "Unknown" },
          ]}
        />
        <Select<LessorFlag | "all">
          value={lessorFlag}
          onChange={(v) => {
            setLessorFlag(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All ownership" },
            { value: "owned", label: "Owned" },
            { value: "lessor", label: "Lessor" },
            { value: "mixed", label: "Mixed" },
            { value: "unknown", label: "Unknown" },
          ]}
        />
        {isFetching && (
          <span className="text-[11px] text-muted-foreground">refreshing…</span>
        )}
      </div>

      {isError && <ErrorBlock message="Couldn't load truck list." />}

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
                  No trucks match the current filters.
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

// Lightweight token-styled select. Hand-rolled — three filter dropdowns
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
    queryFn: () => fetchFleetInsights(10),
  });

  if (isError) return <ErrorBlock message="Couldn't load insights." />;
  if (isLoading || !data) return <SkeletonBlock height="h-64" />;

  const utilizationData = UTILIZATION_ORDER.map((b) => ({
    bucket: b,
    count: data.utilization_breakdown[b],
  }));
  const invoiceData = INVOICE_ORDER.map((b) => ({
    bucket: b,
    count: data.invoice_breakdown[b],
  }));

  return (
    <div className="space-y-6">
      {/* Utilization + Invoicing side-by-side */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Utilization breakdown</h3>
          <p className="mb-3 text-xs text-muted-foreground">
            Trucks per ticket-volume tier. Idle trucks are the alarm
            bucket — they cost money but earn none.
          </p>
          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={utilizationData}
                margin={{ top: 4, right: 8, bottom: 4, left: 0 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="hsl(var(--border))"
                />
                <XAxis
                  dataKey="bucket"
                  tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                  tickFormatter={(b: UtilizationBucket) =>
                    utilizationStyles[b].label
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
                  labelFormatter={(b: UtilizationBucket) =>
                    utilizationStyles[b].label
                  }
                />
                <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                  {utilizationData.map((d) => (
                    <Cell
                      key={d.bucket}
                      fill={toneStyles[utilizationStyles[d.bucket].tone].fill}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div>
          <h3 className="mb-2 text-sm font-semibold">Invoicing breakdown</h3>
          <p className="mb-3 text-xs text-muted-foreground">
            Trucks classified by how complete their A/R is.
          </p>
          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={invoiceData}
                margin={{ top: 4, right: 8, bottom: 4, left: 0 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="hsl(var(--border))"
                />
                <XAxis
                  dataKey="bucket"
                  tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                  tickFormatter={(b: InvoiceBucket) => invoiceStyles[b].label}
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
                  labelFormatter={(b: InvoiceBucket) => invoiceStyles[b].label}
                />
                <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                  {invoiceData.map((d) => (
                    <Cell
                      key={d.bucket}
                      fill={toneStyles[invoiceStyles[d.bucket].tone].fill}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </section>

      {/* Rental-IN summary */}
      <section className="rounded-lg border border-border bg-card p-4">
        <div className="mb-3 flex items-center gap-2">
          <Fuel className="h-4 w-4 text-info" />
          <h4 className="text-sm font-semibold">Rental-in cost</h4>
          <span className="text-[11px] text-muted-foreground">
            (equipment rented FROM external vendors)
          </span>
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <Stat
              label="Contracts"
              value={data.rental_in.contracts.toLocaleString()}
            />
            <Stat
              label="Active"
              value={data.rental_in.active_contracts.toLocaleString()}
              tone={data.rental_in.active_contracts > 0 ? "info" : "neutral"}
            />
            <Stat
              label="RPO"
              value={data.rental_in.rpo_contracts.toLocaleString()}
              tone={data.rental_in.rpo_contracts > 0 ? "warn" : "neutral"}
            />
            <Stat
              label="Monthly cost"
              value={formatCurrency(data.rental_in.total_monthly_cost)}
              tone="info"
            />
            <Stat
              label="Hourly cost"
              value={formatCurrency(data.rental_in.total_hourly_cost)}
            />
          </div>
          <div>
            <h5 className="mb-2 text-xs font-semibold text-muted-foreground">
              Top rental vendors
            </h5>
            {data.rental_in.top_rental_vendors.length === 0 ? (
              <p className="text-xs text-muted-foreground">No data.</p>
            ) : (
              <div className="space-y-1.5">
                {data.rental_in.top_rental_vendors.slice(0, 5).map((v) => (
                  <div
                    key={v.label}
                    className="flex items-center justify-between gap-3 text-xs"
                  >
                    <span className="truncate font-medium" title={v.label}>
                      {v.label}
                    </span>
                    <span className="font-mono tabular-nums text-info">
                      {v.ticket_count.toLocaleString()} contracts ·{" "}
                      {formatCurrency(v.revenue)}/mo
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Top truck money tables */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <TruckMoneyTable
          title="Top revenue"
          icon={<CircleDollarSign className="h-4 w-4 text-primary" />}
          rows={data.top_revenue}
          tone="good"
          formatValue={formatCurrency}
        />
        <TruckMoneyTable
          title="Top uninvoiced A/R"
          icon={<Receipt className="h-4 w-4 text-critical" />}
          rows={data.top_uninvoiced}
          tone="crit"
          formatValue={formatCurrency}
        />
        <TruckMoneyTable
          title="Underused trucks"
          icon={<Clock className="h-4 w-4 text-warning" />}
          rows={data.top_underutilized}
          tone="warn"
          formatValue={(n) => `${n.toLocaleString()} tickets`}
        />
        <MixTable
          title="Top vendors fleet-wide"
          icon={<Users className="h-4 w-4 text-info" />}
          rows={data.top_vendors}
          tone="info"
        />
      </section>

      {/* Top materials + jobs */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <MixTable
          title="Top materials"
          icon={<Activity className="h-4 w-4 text-info" />}
          rows={data.top_materials}
          tone="info"
        />
        <MixTable
          title="Top jobs"
          icon={<Truck className="h-4 w-4 text-primary" />}
          rows={data.top_jobs}
          tone="good"
        />
      </section>

      <div className="text-[11px] text-muted-foreground">
        As of {formatDateTime(data.as_of)} · underused ≤
        {data.underutilized_max_tickets} tickets · heavy ≥
        {data.heavily_utilized_min_tickets} tickets
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

function TruckMoneyTable({
  title,
  icon,
  rows,
  tone,
  formatValue,
}: {
  title: string;
  icon: React.ReactNode;
  rows: { id: string; truck: string; value: number }[];
  tone: Tone;
  formatValue: (n: number) => string;
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
              <span className="truncate font-medium font-mono" title={r.truck}>
                {r.truck}
              </span>
              <span className={cn("font-mono tabular-nums", ts.text)}>
                {formatValue(r.value)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MixTable({
  title,
  icon,
  rows,
  tone,
}: {
  title: string;
  icon: React.ReactNode;
  rows: { label: string; ticket_count: number; revenue: number }[];
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
              key={r.label}
              className="flex items-center justify-between gap-3 text-xs"
            >
              <span className="truncate font-medium" title={r.label}>
                {r.label}
              </span>
              <span className={cn("font-mono tabular-nums", ts.text)}>
                {formatCurrency(r.revenue)}
                <span className="ml-1.5 text-[10px] font-normal text-muted-foreground">
                  {r.ticket_count.toLocaleString()} tk
                </span>
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
          AI-generated next actions for the fleet.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="rounded-lg border border-dashed border-border bg-muted/30 p-4 text-center">
          <p className="text-sm font-medium">Coming in Phase 6</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Claude will rank uninvoiced A/R by collection probability,
            flag idle trucks for redeployment, and suggest rental-in
            consolidation across vendors — directly in this panel.
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

function formatCurrency(n: number): string {
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

function formatNumber(n: number): string {
  return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
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
