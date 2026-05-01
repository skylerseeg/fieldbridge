import { type ReactNode, useMemo, useState } from "react";
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
  Check,
  ChevronLeft,
  ChevronRight,
  Clock,
  Compass,
  Fuel,
  MapPin,
  Radio,
  Wrench,
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
import { RecommendationsRail as SharedRecommendationsRail } from "@/components/RecommendationsRail";
import { cn } from "@/lib/utils";

import {
  fetchEquipmentInsights,
  fetchEquipmentList,
  fetchEquipmentStatus,
  fetchEquipmentSummary,
  type EquipmentListRow,
  type EquipmentStatusRow,
  type ListParams,
  type OwnershipKind,
  type SortDir,
  type SortField,
  type StatusParams,
  type UtilizationBucket,
} from "./equipment-api";

/**
 * Equipment module — Phase 5 page.
 *
 * Layout:
 *   ┌── 4 KPI tiles ───────────────────────────────────┐ ┌── Recommendations
 *   │  Total · 30d activity · Owned · Rented           │ │   (right rail)
 *   ├── Tabs: Overview · List · Insights ──────────────┤ │
 *   │  Overview: utilization bucket bar + summary      │ │
 *   │  List:     paginated TanStack table              │ │
 *   │  Insights: fuel $/hr + owned-vs-rented           │ │
 *   └──────────────────────────────────────────────────┘ └──────────────────
 *
 * Data flow:
 *   - All reads hit the shared `api` axios instance, which already handles
 *     token attach + 401-refresh.
 *   - List filters/sort/page are component state and become part of the
 *     useQuery key — so any change re-fetches.
 *   - `keepPreviousData` smooths over pagination so the table doesn't
 *     "blink" between pages.
 *
 * Mutations:
 *   The Phase 5 brief calls for "TanStack Query mutations with optimistic
 *   updates where safe" — but the equipment endpoints are read-only. No
 *   write surface exists yet, so no useMutation calls are wired here.
 *   When write actions land (e.g. retire asset, change ownership), they
 *   go through `useMutation` with onMutate-cancel-snapshot-set pattern,
 *   keyed off the same query keys defined in `keys.list(params)` below.
 */

// Shared severity → token-class map. Tile borders, bucket-bar fills, and
// list-row chips all derive from this — keeps the four buckets consistent.
const bucketStyles: Record<
  UtilizationBucket,
  {
    border: string;
    bg: string;
    text: string;
    fill: string; // raw hsl() for recharts
    label: string;
    Icon: typeof Check;
  }
> = {
  good: {
    border: "border-l-primary",
    bg: "bg-primary/10",
    text: "text-primary",
    fill: "hsl(var(--primary))",
    label: "Good standing",
    Icon: Check,
  },
  under: {
    border: "border-l-info",
    bg: "bg-info/10",
    text: "text-info",
    fill: "hsl(var(--info))",
    label: "Under utilized",
    Icon: Compass,
  },
  excessive: {
    border: "border-l-warning",
    bg: "bg-warning/10",
    text: "text-warning",
    fill: "hsl(var(--warning))",
    label: "Excessive use",
    Icon: AlertTriangle,
  },
  issues: {
    border: "border-l-critical",
    bg: "bg-critical/10",
    text: "text-critical",
    fill: "hsl(var(--critical))",
    label: "Issues reported",
    Icon: Wrench,
  },
};

// Query key factory — keeps invalidations consistent across hooks.
const keys = {
  all: ["equipment"] as const,
  summary: () => [...keys.all, "summary"] as const,
  list: (params: ListParams) => [...keys.all, "list", params] as const,
  status: (params: StatusParams) => [...keys.all, "status", params] as const,
  insights: (topN: number) => [...keys.all, "insights", topN] as const,
};

// ──────────────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────────────

export function EquipmentPage() {
  return (
    <div className="p-6 lg:p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Equipment</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Fleet utilization, ticket activity, and rental exposure across every
          owned and rented asset.
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
// KPI tiles row
// ──────────────────────────────────────────────────────────────────────

function KpiTiles() {
  const { data, isLoading, isError } = useQuery({
    queryKey: keys.summary(),
    queryFn: fetchEquipmentSummary,
  });

  // Four buckets become four severity-coded tiles. Total / 30d / Owned /
  // Rented show as smaller header badges so the bucket counts get top
  // billing — they're the actionable numbers.
  const tiles = useMemo(() => {
    if (!data) return [];
    return [
      {
        bucket: "good" as const,
        count: data.bucket_good,
        sub: `of ${data.total_assets} assets`,
      },
      {
        bucket: "under" as const,
        count: data.bucket_under,
        sub: "no recent tickets",
      },
      {
        bucket: "excessive" as const,
        count: data.bucket_excessive,
        sub: "above hour threshold",
      },
      {
        bucket: "issues" as const,
        count: data.bucket_issues,
        sub: "needs attention",
      },
    ];
  }, [data]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Fleet utilization</CardTitle>
          <CardDescription>
            Last 30 days · pulled from the equipment mart
          </CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          {data && (
            <>
              <Badge variant="mono">
                {data.total_assets} total
              </Badge>
              <Badge variant="mono">
                {data.tickets_30d} tickets · 30d
              </Badge>
              <Badge variant="mono">
                {formatCurrency(data.revenue_30d)} · 30d
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
              const s = bucketStyles[t.bucket];
              return (
                <div
                  key={t.bucket}
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
                    <s.Icon className={cn("h-3.5 w-3.5", s.text)} />
                  </div>
                  <div className="font-mono text-2xl font-semibold">
                    {t.count}
                  </div>
                  <div className="text-xs font-medium">{s.label}</div>
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
// Tabbed content area
// ──────────────────────────────────────────────────────────────────────

function ContentTabs() {
  return (
    <Card>
      <Tabs defaultValue="status" className="w-full">
        <CardHeader className="space-y-3">
          <TabsList className="flex h-auto flex-wrap justify-start">
            <TabsTrigger value="status">Status</TabsTrigger>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="list">List</TabsTrigger>
            <TabsTrigger value="insights">Insights</TabsTrigger>
          </TabsList>
        </CardHeader>
        <CardContent>
          <TabsContent value="status" className="mt-0">
            <StatusTab />
          </TabsContent>
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

// ── Status board ─────────────────────────────────────────────────────

function StatusTab() {
  const [search, setSearch] = useState("");
  const [bucket, setBucket] = useState<UtilizationBucket | "all">("all");
  const [staleOnly, setStaleOnly] = useState(false);
  const [includeRetired, setIncludeRetired] = useState(true);

  const params: StatusParams = useMemo(
    () => ({
      page: 1,
      page_size: 100,
      include_retired: includeRetired,
      stale_only: staleOnly || undefined,
      ...(search.trim() ? { search: search.trim() } : {}),
      ...(bucket !== "all" ? { bucket } : {}),
    }),
    [bucket, includeRetired, search, staleOnly],
  );

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: keys.status(params),
    queryFn: () => fetchEquipmentStatus(params),
    placeholderData: keepPreviousData,
  });

  const staleRows = data?.items.filter((item) => item.stale_ticket) ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-xl border border-border bg-muted/20 p-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Radio className="h-4 w-4 text-primary" />
            <h3 className="text-base font-semibold">Equipment Status Board</h3>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            Live field posture from mart_equipment_utilization,
            mart_work_orders, mart_equipment_transfers, and
            mart_asset_barcodes.
          </p>
        </div>
        {data && (
          <Badge variant="mono">
            {data.total.toLocaleString()} assets · as of{" "}
            {formatDateTime(data.as_of)}
          </Badge>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search asset name…"
          className="min-h-11 w-full text-base sm:w-72"
        />
        <Select<UtilizationBucket | "all">
          value={bucket}
          onChange={setBucket}
          options={[
            { value: "all", label: "All buckets" },
            { value: "good", label: "Good standing" },
            { value: "under", label: "Under utilized" },
            { value: "excessive", label: "Excessive use" },
            { value: "issues", label: "Issues reported" },
          ]}
        />
        <Button
          type="button"
          variant={staleOnly ? "default" : "outline"}
          size="sm"
          className="min-h-11"
          onClick={() => setStaleOnly((v) => !v)}
        >
          Stale tickets
        </Button>
        <Button
          type="button"
          variant={includeRetired ? "outline" : "secondary"}
          size="sm"
          className="min-h-11"
          onClick={() => setIncludeRetired((v) => !v)}
        >
          {includeRetired ? "Hide retired" : "Show retired"}
        </Button>
        {isFetching && (
          <span className="text-[11px] text-muted-foreground">refreshing…</span>
        )}
      </div>

      {isError && <ErrorBlock message="Couldn't load equipment status." />}
      {isLoading && <SkeletonGrid count={4} />}

      {data && staleRows.length > 0 && (
        <section className="rounded-xl border border-warning/30 bg-warning/10 p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-warning">
                Stale ticket alert lane
              </h3>
              <p className="text-xs text-muted-foreground">
                No mart_equipment_utilization ticket in{" "}
                {data.stale_threshold_days}+ days and not retired.
              </p>
            </div>
            <Badge variant="outline">{staleRows.length} assets</Badge>
          </div>
          <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
            {staleRows.slice(0, 6).map((row) => (
              <StatusMiniRow key={row.id} row={row} />
            ))}
          </div>
        </section>
      )}

      {data && data.items.length === 0 && (
        <div className="rounded-lg border border-border p-6 text-center text-sm text-muted-foreground">
          No assets match the current status filters.
        </div>
      )}

      {data && data.items.length > 0 && (
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {data.items.map((row) => (
            <StatusCard key={row.id} row={row} />
          ))}
        </div>
      )}
    </div>
  );
}

function StatusCard({ row }: { row: EquipmentStatusRow }) {
  const s = bucketStyles[row.bucket];
  return (
    <article
      className={cn(
        "rounded-xl border border-border border-l-4 bg-card p-4 shadow-sm",
        "min-h-36",
        s.border,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-xl font-semibold tracking-tight">{row.truck}</h3>
          <div className="mt-1 flex flex-wrap gap-2">
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold",
                s.bg,
                s.text,
              )}
            >
              <s.Icon className="h-3.5 w-3.5" />
              {s.label}
            </span>
            {row.stale_ticket && (
              <Badge variant="outline" className="border-warning text-warning">
                stale ticket
              </Badge>
            )}
            {row.retired && (
              <Badge variant="destructive">retired</Badge>
            )}
          </div>
        </div>
        <Badge variant={row.ownership === "owned" ? "secondary" : "outline"}>
          {row.ownership}
        </Badge>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
        <FieldBlock
          icon={<Wrench className="h-4 w-4" />}
          label="Current job"
          value={formatCurrentJob(row)}
          sub={row.current_job.description ?? undefined}
        />
        <FieldBlock
          icon={<Clock className="h-4 w-4" />}
          label="Last ticket"
          value={formatIdle(row)}
          sub={`${row.tickets.toLocaleString()} total tickets`}
        />
        <FieldBlock
          icon={<MapPin className="h-4 w-4" />}
          label="Last transfer"
          value={row.last_transfer.location ?? "No transfer"}
          sub={formatDate(row.last_transfer.transfer_date)}
        />
      </div>
    </article>
  );
}

function StatusMiniRow({ row }: { row: EquipmentStatusRow }) {
  return (
    <div className="rounded-lg border border-warning/20 bg-card/80 p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold">{row.truck}</div>
          <div className="text-xs text-muted-foreground">
            {formatIdle(row)} · {formatCurrentJob(row)}
          </div>
        </div>
        <Badge variant="outline" className="border-warning text-warning">
          {row.days_since_last_ticket ?? "No"} d
        </Badge>
      </div>
    </div>
  );
}

function FieldBlock({
  icon,
  label,
  value,
  sub,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-lg bg-muted/30 p-3">
      <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        {icon}
        {label}
      </div>
      <div className="font-mono text-sm font-semibold tabular-nums">{value}</div>
      {sub && <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}

// ── Overview ─────────────────────────────────────────────────────────

function OverviewTab() {
  const { data, isLoading, isError } = useQuery({
    queryKey: keys.summary(),
    queryFn: fetchEquipmentSummary,
  });

  if (isError) return <ErrorBlock message="Couldn't load overview." />;
  if (isLoading || !data) return <SkeletonBlock height="h-64" />;

  const chartData = [
    { bucket: "good" as const, count: data.bucket_good },
    { bucket: "under" as const, count: data.bucket_under },
    { bucket: "excessive" as const, count: data.bucket_excessive },
    { bucket: "issues" as const, count: data.bucket_issues },
  ];

  const ownedShare =
    data.total_assets > 0 ? data.owned_assets / data.total_assets : 0;
  const rentedShare =
    data.total_assets > 0 ? data.rented_assets / data.total_assets : 0;

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
      <div className="md:col-span-2">
        <h3 className="text-sm font-semibold">Utilization distribution</h3>
        <p className="mb-3 text-xs text-muted-foreground">
          Asset count per bucket.
        </p>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={chartData}
              margin={{ top: 8, right: 8, bottom: 8, left: 0 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="hsl(var(--border))"
              />
              <XAxis
                dataKey="bucket"
                tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                tickFormatter={(b: UtilizationBucket) => bucketStyles[b].label}
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
                  bucketStyles[b].label
                }
              />
              <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                {chartData.map((d) => (
                  <Cell
                    key={d.bucket}
                    fill={bucketStyles[d.bucket].fill}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-semibold">Mix</h3>
        <SummaryRow
          label="Owned"
          value={`${data.owned_assets}`}
          sub={formatPercent(ownedShare)}
        />
        <SummaryRow
          label="Rented"
          value={`${data.rented_assets}`}
          sub={formatPercent(rentedShare)}
        />
        <div className="border-t border-border pt-3" />
        <SummaryRow
          label="Tickets · 30d"
          value={data.tickets_30d.toLocaleString()}
        />
        <SummaryRow
          label="Revenue · 30d"
          value={formatCurrency(data.revenue_30d)}
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
      <span className="font-mono text-base font-semibold tabular-nums">
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
  const [bucket, setBucket] = useState<UtilizationBucket | "all">("all");
  const [ownership, setOwnership] = useState<OwnershipKind | "all">("all");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [sorting, setSorting] = useState<SortingState>([
    { id: "last_ticket_date", desc: true },
  ]);

  const sortBy = (sorting[0]?.id ?? "last_ticket_date") as SortField;
  const sortDir: SortDir = sorting[0]?.desc ? "desc" : "asc";

  const params: ListParams = useMemo(
    () => ({
      page,
      page_size: pageSize,
      sort_by: sortBy,
      sort_dir: sortDir,
      ...(search.trim() ? { search: search.trim() } : {}),
      ...(bucket !== "all" ? { bucket } : {}),
      ...(ownership !== "all" ? { ownership } : {}),
    }),
    [page, pageSize, sortBy, sortDir, search, bucket, ownership],
  );

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: keys.list(params),
    queryFn: () => fetchEquipmentList(params),
    placeholderData: keepPreviousData,
  });

  const columns = useMemo<ColumnDef<EquipmentListRow>[]>(
    () => [
      {
        accessorKey: "truck",
        header: "Asset",
        cell: ({ row }) => (
          <div className="flex flex-col">
            <span className="font-medium">{row.original.truck}</span>
            <span className="text-[11px] text-muted-foreground">
              {row.original.id}
            </span>
          </div>
        ),
      },
      {
        accessorKey: "ownership",
        header: "Ownership",
        enableSorting: false,
        cell: ({ row }) => (
          <Badge
            variant={row.original.ownership === "owned" ? "secondary" : "outline"}
          >
            {row.original.ownership}
          </Badge>
        ),
      },
      {
        accessorKey: "bucket",
        header: "Bucket",
        enableSorting: false,
        cell: ({ row }) => {
          const s = bucketStyles[row.original.bucket];
          return (
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium",
                s.bg,
                s.text,
              )}
            >
              <s.Icon className="h-3 w-3" />
              {s.label}
            </span>
          );
        },
      },
      {
        accessorKey: "tickets",
        header: "Tickets",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums">
            {row.original.tickets.toLocaleString()}
          </span>
        ),
      },
      {
        accessorKey: "total_qty",
        header: "Total qty",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums">
            {row.original.total_qty.toLocaleString(undefined, {
              maximumFractionDigits: 1,
            })}
          </span>
        ),
      },
      {
        accessorKey: "total_revenue",
        header: "Revenue",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums">
            {formatCurrency(row.original.total_revenue)}
          </span>
        ),
      },
      {
        accessorKey: "last_ticket_date",
        header: "Last ticket",
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">
            {formatDate(row.original.last_ticket_date)}
          </span>
        ),
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
      // Reset to page 1 whenever the sort order changes — otherwise the
      // user lands on a now-stale page index that may not exist.
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
          placeholder="Search asset name…"
          className="w-full sm:w-64"
        />
        <Select<UtilizationBucket | "all">
          value={bucket}
          onChange={(v) => {
            setBucket(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All buckets" },
            { value: "good", label: "Good standing" },
            { value: "under", label: "Under utilized" },
            { value: "excessive", label: "Excessive use" },
            { value: "issues", label: "Issues reported" },
          ]}
        />
        <Select<OwnershipKind | "all">
          value={ownership}
          onChange={(v) => {
            setOwnership(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All ownership" },
            { value: "owned", label: "Owned" },
            { value: "rented", label: "Rented" },
          ]}
        />
        {isFetching && (
          <span className="text-[11px] text-muted-foreground">refreshing…</span>
        )}
      </div>

      {isError && <ErrorBlock message="Couldn't load equipment list." />}

      <div className="grid grid-cols-1 gap-3 md:hidden">
        {isLoading ? (
          <SkeletonGrid count={3} />
        ) : table.getRowModel().rows.length === 0 ? (
          <div className="rounded-lg border border-border p-6 text-center text-sm text-muted-foreground">
            No assets match the current filters.
          </div>
        ) : (
          table.getRowModel().rows.map((row) => (
            <MobileAssetCard key={row.id} row={row.original} />
          ))
        )}
      </div>

      <div className="hidden rounded-lg border border-border md:block">
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
                  No assets match the current filters.
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

function MobileAssetCard({ row }: { row: EquipmentListRow }) {
  const s = bucketStyles[row.bucket];
  return (
    <article className={cn("rounded-xl border border-border border-l-4 bg-card p-4", s.border)}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold">{row.truck}</h3>
          <div className="mt-1 text-xs text-muted-foreground">
            Last ticket {formatDate(row.last_ticket_date)}
          </div>
        </div>
        <Badge variant={row.ownership === "owned" ? "secondary" : "outline"}>
          {row.ownership}
        </Badge>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
            s.bg,
            s.text,
          )}
        >
          <s.Icon className="h-3 w-3" />
          {s.label}
        </span>
        <Badge variant="mono">{row.tickets.toLocaleString()} tickets</Badge>
        <Badge variant="mono">{formatCurrency(row.total_revenue)}</Badge>
      </div>
    </article>
  );
}

// Lightweight token-styled select. Hand-rolled instead of pulling in
// another Radix primitive — three filter dropdowns don't justify the
// surface area.
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
    queryKey: keys.insights(20),
    queryFn: () => fetchEquipmentInsights(20),
  });

  if (isError) return <ErrorBlock message="Couldn't load insights." />;
  if (isLoading || !data) return <SkeletonBlock height="h-64" />;

  const fuelData = data.fuel_cost_per_hour_by_asset.slice(0, 12);

  return (
    <div className="space-y-6">
      {/* Fuel $/hr */}
      <section>
        <div className="mb-2 flex items-center gap-2">
          <Fuel className="h-4 w-4 text-warning" />
          <h3 className="text-sm font-semibold">Fuel cost per hour · top 12</h3>
        </div>
        <p className="mb-3 text-xs text-muted-foreground">
          Revenue ÷ recorded hours, descending.
        </p>
        <div className="h-72 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={fuelData}
              layout="vertical"
              margin={{ top: 4, right: 16, bottom: 4, left: 96 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="hsl(var(--border))"
                horizontal={false}
              />
              <XAxis
                type="number"
                tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                stroke="hsl(var(--border))"
                tickFormatter={(v: number) => `$${v.toFixed(0)}`}
              />
              <YAxis
                type="category"
                dataKey="truck"
                width={88}
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
                formatter={(v: number) => [`$${v.toFixed(2)}/hr`, "Cost"]}
              />
              <Bar
                dataKey="cost_per_hour"
                fill="hsl(var(--warning))"
                radius={[0, 6, 6, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* Owned vs rented */}
      <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-border bg-card p-4">
          <h4 className="mb-3 text-sm font-semibold">Owned</h4>
          <Stat label="Assets" value={data.rental_vs_owned.owned.count} />
          <Stat
            label="Tickets"
            value={data.rental_vs_owned.owned.total_tickets}
          />
          <Stat
            label="Revenue"
            value={formatCurrency(data.rental_vs_owned.owned.total_revenue)}
          />
          <Stat
            label="Avg tickets / asset"
            value={data.rental_vs_owned.owned.avg_tickets_per_asset.toFixed(1)}
          />
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <h4 className="mb-3 text-sm font-semibold">Rented</h4>
          <Stat label="Assets" value={data.rental_vs_owned.rented.count} />
          <Stat
            label="Active rentals"
            value={data.rental_vs_owned.rented.active_rentals}
          />
          <Stat
            label="Total committed"
            value={formatCurrency(
              data.rental_vs_owned.rented.total_rate_committed,
            )}
          />
          <Stat
            label="Avg rate"
            value={formatCurrency(data.rental_vs_owned.rented.avg_rate)}
          />
        </div>
      </section>

      {/* Bucket breakdown — small chips */}
      <section>
        <h3 className="mb-2 text-sm font-semibold">Utilization buckets</h3>
        <div className="flex flex-wrap gap-2">
          {(["good", "under", "excessive", "issues"] as const).map((b) => {
            const s = bucketStyles[b];
            const count = data.utilization_buckets[b];
            return (
              <span
                key={b}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
                  s.bg,
                  s.text,
                )}
              >
                <s.Icon className="h-3 w-3" />
                {s.label}
                <span className="font-mono">{count}</span>
              </span>
            );
          })}
        </div>
      </section>

      <div className="text-[11px] text-muted-foreground">
        As of {formatDateTime(data.as_of)}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="font-mono text-sm font-semibold tabular-nums">
        {typeof value === "number" ? value.toLocaleString() : value}
      </span>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Right rail: Recommendations — Phase 6 LLM panel
// ──────────────────────────────────────────────────────────────────────
//
// Delegates to the shared `RecommendationsRail` so every module gets the
// same loading/error/stub treatment. The slug must match the FastAPI
// mount in `app/main.py` — `equipment` here.

function RecommendationsRail() {
  return (
    <div className="space-y-4">
      <StaleTicketRailLane />
      <SharedRecommendationsRail
        moduleSlug="equipment"
        description="Claude-ranked next actions for your fleet, refreshed every 6 hours."
      />
    </div>
  );
}

function StaleTicketRailLane() {
  const params: StatusParams = useMemo(
    () => ({ page: 1, page_size: 5, stale_only: true, include_retired: false }),
    [],
  );
  const { data, isLoading, isError } = useQuery({
    queryKey: keys.status(params),
    queryFn: () => fetchEquipmentStatus(params),
  });

  if (isError) return null;

  return (
    <Card className="border-warning/30">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm text-warning">Stale tickets</CardTitle>
        <CardDescription>
          Assets with no mart_equipment_utilization ticket in 14+ days.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {isLoading && <SkeletonBlock height="h-20" />}
        {data && data.items.length === 0 && (
          <p className="text-xs text-muted-foreground">
            No stale ticket alerts right now.
          </p>
        )}
        {data?.items.map((row) => (
          <StatusMiniRow key={row.id} row={row} />
        ))}
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

function formatPercent(n: number): string {
  return `${(n * 100).toFixed(0)}%`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString();
}

function formatCurrentJob(row: EquipmentStatusRow): string {
  const job = row.current_job.job_number ?? "No job";
  const wo = row.current_job.work_order ? `WO ${row.current_job.work_order}` : "No WO";
  const status = row.current_job.status ?? "unknown";
  return `${job} · ${wo} · ${status}`;
}

function formatIdle(row: EquipmentStatusRow): string {
  if (row.days_since_last_ticket === null) return "No ticket on file";
  return `${formatDate(row.last_ticket_date)} · ${row.days_since_last_ticket}d ago`;
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}
