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
  Building2,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  Droplets,
  FileText,
  Hammer,
  HelpCircle,
  Layers,
  Map,
  MapPin,
  Mountain,
  Sparkles,
  Square,
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
  fetchProposalsInsights,
  fetchProposalsList,
  fetchProposalsSummary,
  type BidTypeCategory,
  type GeographyTier,
  type ListParams,
  type ProposalListRow,
  type SortDir,
  type SortField,
} from "./proposals-api";

/**
 * Proposals module — Phase 5 page.
 *
 * Layout:
 *   ┌── 4 KPI tiles (proposals) ───────────────────────┐ ┌── Recommendations
 *   │  Proposals · In-state · Line items · Avg budget  │ │   (right rail)
 *   ├── Tabs: Overview · List · Insights ──────────────┤ │
 *   │  Overview: bid-type category mix + activity      │ │
 *   │  List:     paginated TanStack table              │ │
 *   │  Insights: category + geography breakdowns,      │ │
 *   │            top owners / bid types / counties,    │ │
 *   │            top states, competitor frequency,     │ │
 *   │            fee statistics                        │ │
 *   └──────────────────────────────────────────────────┘ └──────────────────
 *
 * One row per proposal header — keyed (job, owner, bid_type). Two
 * derived classifications:
 *   - bid type category (pressurized / structures / concrete /
 *     earthwork / other)
 *   - geography tier (in_state / out_of_state / unknown vs. tenant
 *     primary state, default UT)
 *
 * Severity → token mapping (no new colors):
 *   primary  = good / dominant healthy bucket
 *   info     = neutral fact (counts, geography facts)
 *   warning  = caution (concrete-heavy, mid in-state share)
 *   critical = alert (earthwork — narrow speciality)
 *
 * Mutations: proposals endpoints are read-only. Query-key factory is
 * ready for Phase 6 (e.g. flagging owners for outreach).
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

const categoryStyles: Record<
  BidTypeCategory,
  { tone: Tone; label: string; Icon: typeof Droplets }
> = {
  pressurized: { tone: "info", label: "Pressurized", Icon: Droplets },
  structures: { tone: "good", label: "Structures", Icon: Building2 },
  concrete: { tone: "warn", label: "Concrete", Icon: Square },
  earthwork: { tone: "crit", label: "Earthwork", Icon: Mountain },
  other: { tone: "neutral", label: "Other", Icon: Hammer },
};

const geographyStyles: Record<
  GeographyTier,
  { tone: Tone; label: string; Icon: typeof MapPin }
> = {
  in_state: { tone: "good", label: "In-state", Icon: MapPin },
  out_of_state: { tone: "info", label: "Out-of-state", Icon: Map },
  unknown: { tone: "neutral", label: "Unknown", Icon: HelpCircle },
};

// Display order for stacks.
const CATEGORY_ORDER: BidTypeCategory[] = [
  "pressurized",
  "structures",
  "concrete",
  "earthwork",
  "other",
];
const GEOGRAPHY_ORDER: GeographyTier[] = [
  "in_state",
  "out_of_state",
  "unknown",
];

// Friendly labels for the fee_statistics rows.
const FEE_LABELS: Record<string, string> = {
  design_fee: "Design fee",
  cm_fee: "CM fee",
  cm_monthly_fee: "CM monthly",
  contractor_ohp_fee: "OH&P fee",
  contractor_bonds_ins: "Bonds & ins.",
  contractor_co_markup: "CO markup",
  city_budget: "City budget",
};

// Query key factory.
const keys = {
  all: ["proposals"] as const,
  summary: () => [...keys.all, "summary"] as const,
  list: (params: ListParams) => [...keys.all, "list", params] as const,
  insights: (topN: number) => [...keys.all, "insights", topN] as const,
};

// ──────────────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────────────

export function ProposalsPage() {
  return (
    <div className="p-6 lg:p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Proposals</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Proposal headers from the bidding pipeline — owner, bid type,
          and geography against the tenant's primary state.
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
    queryFn: fetchProposalsSummary,
  });

  // Four proposal-oriented tiles. Severity adapts:
  //   - Proposals: info (raw count).
  //   - In-state share: ≥60% good · ≥30% info · else neutral; neutral when 0.
  //   - Line items: info — neutral fact.
  //   - Avg city budget: info; neutral when no budget data.
  const tiles = useMemo(() => {
    if (!data) return [];

    const inStateShare =
      data.total_proposals > 0
        ? data.in_state_proposals / data.total_proposals
        : 0;
    const inStateTone: Tone =
      data.total_proposals === 0
        ? "neutral"
        : inStateShare >= 0.6
          ? "good"
          : inStateShare >= 0.3
            ? "info"
            : "neutral";

    return [
      {
        key: "proposals",
        tone: "info" as Tone,
        Icon: FileText,
        value: data.total_proposals.toLocaleString(),
        label: "Proposals",
        sub: `${data.distinct_owners.toLocaleString()} owners · ${data.distinct_bid_types.toLocaleString()} bid types`,
      },
      {
        key: "in_state",
        tone: inStateTone,
        Icon: MapPin,
        value:
          data.total_proposals > 0
            ? `${(inStateShare * 100).toFixed(0)}%`
            : "—",
        label: "In-state share",
        sub:
          data.total_proposals > 0
            ? `${data.in_state_proposals.toLocaleString()} of ${data.total_proposals.toLocaleString()}`
            : "no proposals",
      },
      {
        key: "line_items",
        tone:
          data.total_line_items > 0 ? ("info" as Tone) : ("neutral" as Tone),
        Icon: Layers,
        value: data.total_line_items.toLocaleString(),
        label: "Line items",
        sub:
          data.total_line_items > 0
            ? `${data.distinct_competitors.toLocaleString()} competitors tracked`
            : "no line items",
      },
      {
        key: "avg_budget",
        tone:
          data.avg_city_budget > 0 ? ("info" as Tone) : ("neutral" as Tone),
        Icon: CircleDollarSign,
        value: data.avg_city_budget > 0 ? formatMoney(data.avg_city_budget) : "—",
        label: "Avg city budget",
        sub:
          data.avg_city_budget > 0
            ? `${formatMoney(data.total_city_budget)} total`
            : "no budget data",
      },
    ];
  }, [data]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Proposal snapshot</CardTitle>
          <CardDescription>
            Header rollup · pulled from the proposals marts
          </CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          {data && (
            <>
              <Badge variant="mono">
                {data.distinct_counties.toLocaleString()} counties
              </Badge>
              <Badge variant="mono">
                {data.distinct_states.toLocaleString()} states
              </Badge>
              <Badge variant="mono">
                {data.line_items_with_competitor.toLocaleString()} w/ comp.
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
    queryFn: fetchProposalsSummary,
  });
  const insights = useQuery({
    queryKey: keys.insights(10),
    queryFn: () => fetchProposalsInsights(10),
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

  // Headline: proposal count by bid-type category.
  const categoryChart = CATEGORY_ORDER.map((k) => ({
    key: k,
    label: categoryStyles[k].label,
    value: i.bid_type_category_breakdown[k],
    tone: categoryStyles[k].tone,
  }));

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
      <div className="md:col-span-2">
        <h3 className="text-sm font-semibold">Bid-type category mix</h3>
        <p className="mb-3 text-xs text-muted-foreground">
          Proposals bucketed by free-form bid type across{" "}
          {s.total_proposals.toLocaleString()} headers.
        </p>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={categoryChart}
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
                {categoryChart.map((d) => (
                  <Cell key={d.key} fill={toneStyles[d.tone].fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-semibold">Activity</h3>
        <SummaryRow
          label="Proposals"
          value={s.total_proposals.toLocaleString()}
        />
        <SummaryRow
          label="Owners"
          value={s.distinct_owners.toLocaleString()}
        />
        <SummaryRow
          label="Bid types"
          value={s.distinct_bid_types.toLocaleString()}
        />
        <div className="border-t border-border pt-3" />
        <h3 className="text-sm font-semibold">Geography</h3>
        <SummaryRow
          label="In-state"
          value={s.in_state_proposals.toLocaleString()}
          sub={shareSub(s.in_state_proposals, s.total_proposals)}
        />
        <SummaryRow
          label="Out-of-state"
          value={s.out_of_state_proposals.toLocaleString()}
          sub={shareSub(s.out_of_state_proposals, s.total_proposals)}
        />
        <SummaryRow
          label="Unknown"
          value={s.unknown_geography_proposals.toLocaleString()}
          sub={shareSub(s.unknown_geography_proposals, s.total_proposals)}
        />
        <div className="border-t border-border pt-3" />
        <h3 className="text-sm font-semibold">Line items</h3>
        <SummaryRow
          label="Total"
          value={s.total_line_items.toLocaleString()}
        />
        <SummaryRow
          label="With competitor"
          value={s.line_items_with_competitor.toLocaleString()}
          sub={shareSub(s.line_items_with_competitor, s.total_line_items)}
        />
        <SummaryRow
          label="Distinct competitors"
          value={s.distinct_competitors.toLocaleString()}
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
  const [category, setCategory] = useState<BidTypeCategory | "all">("all");
  const [geography, setGeography] = useState<GeographyTier | "all">("all");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [sorting, setSorting] = useState<SortingState>([
    { id: "job", desc: false },
  ]);

  const sortBy = (sorting[0]?.id ?? "job") as SortField;
  const sortDir: SortDir = sorting[0]?.desc ? "desc" : "asc";

  const params: ListParams = useMemo(
    () => ({
      page,
      page_size: pageSize,
      sort_by: sortBy,
      sort_dir: sortDir,
      ...(search.trim() ? { search: search.trim() } : {}),
      ...(category !== "all" ? { bid_type_category: category } : {}),
      ...(geography !== "all" ? { geography_tier: geography } : {}),
    }),
    [page, pageSize, sortBy, sortDir, search, category, geography],
  );

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: keys.list(params),
    queryFn: () => fetchProposalsList(params),
    placeholderData: keepPreviousData,
  });

  const columns = useMemo<ColumnDef<ProposalListRow>[]>(
    () => [
      {
        accessorKey: "job",
        header: "Job",
        cell: ({ row }) => (
          <span className="font-mono text-xs font-medium">
            {row.original.job}
          </span>
        ),
      },
      {
        accessorKey: "owner",
        header: "Owner",
        enableSorting: true,
        cell: ({ row }) => (
          <span
            className="line-clamp-2 text-xs"
            title={row.original.owner}
          >
            {row.original.owner}
          </span>
        ),
      },
      {
        accessorKey: "bid_type",
        header: "Bid type",
        cell: ({ row }) => {
          const c = categoryStyles[row.original.bid_type_category];
          const ts = toneStyles[c.tone];
          return (
            <div className="flex flex-col gap-0.5">
              <span
                className="line-clamp-2 text-xs"
                title={row.original.bid_type}
              >
                {row.original.bid_type}
              </span>
              <span
                className={cn(
                  "inline-flex w-fit items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                  ts.bg,
                  ts.text,
                )}
              >
                <c.Icon className="h-3 w-3" />
                {c.label}
              </span>
            </div>
          );
        },
      },
      {
        accessorKey: "county",
        header: "County",
        cell: ({ row }) => (
          <div className="flex flex-col gap-0.5">
            <span className="text-xs">
              {row.original.county ?? (
                <span className="text-muted-foreground">—</span>
              )}
            </span>
            {row.original.state_code && (
              <span className="font-mono text-[10px] text-muted-foreground">
                {row.original.state_code}
              </span>
            )}
          </div>
        ),
      },
      {
        id: "geography_tier",
        accessorKey: "geography_tier",
        header: "Geography",
        enableSorting: false,
        cell: ({ row }) => {
          const g = geographyStyles[row.original.geography_tier];
          const ts = toneStyles[g.tone];
          return (
            <span
              className={cn(
                "inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
                ts.bg,
                ts.text,
              )}
            >
              <g.Icon className="h-3 w-3" />
              {g.label}
            </span>
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
          placeholder="Search job, owner, bid type, county…"
          className="w-full sm:w-72"
        />
        <Select<BidTypeCategory | "all">
          value={category}
          onChange={(v) => {
            setCategory(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All categories" },
            { value: "pressurized", label: "Pressurized" },
            { value: "structures", label: "Structures" },
            { value: "concrete", label: "Concrete" },
            { value: "earthwork", label: "Earthwork" },
            { value: "other", label: "Other" },
          ]}
        />
        <Select<GeographyTier | "all">
          value={geography}
          onChange={(v) => {
            setGeography(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All geography" },
            { value: "in_state", label: "In-state" },
            { value: "out_of_state", label: "Out-of-state" },
            { value: "unknown", label: "Unknown" },
          ]}
        />
        {isFetching && (
          <span className="text-[11px] text-muted-foreground">refreshing…</span>
        )}
      </div>

      {isError && <ErrorBlock message="Couldn't load proposal list." />}

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
                  No proposals match the current filters.
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
    queryFn: () => fetchProposalsInsights(10),
  });

  if (isError) return <ErrorBlock message="Couldn't load insights." />;
  if (isLoading || !data) return <SkeletonBlock height="h-64" />;

  const categoryChart = CATEGORY_ORDER.map((k) => ({
    key: k,
    label: categoryStyles[k].label,
    value: data.bid_type_category_breakdown[k],
    tone: categoryStyles[k].tone,
  }));

  const geographyChart = GEOGRAPHY_ORDER.map((k) => ({
    key: k,
    label: geographyStyles[k].label,
    value: data.geography_tier_breakdown[k],
    tone: geographyStyles[k].tone,
  }));

  const competitorChart = data.competitor_frequency
    .slice(0, 10)
    .map((c) => ({
      label: truncate(c.competitor, 24),
      value: c.line_item_count,
    }));

  return (
    <div className="space-y-6">
      {/* Category + Geography breakdowns */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <BreakdownChart
          title="Bid-type category"
          subtitle="Proposals bucketed by free-form bid type."
          data={categoryChart}
        />
        <BreakdownChart
          title="Geography tier"
          subtitle="Proposals against the tenant's primary state."
          data={geographyChart}
        />
      </section>

      {/* Top owners / bid types / counties */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <SegmentTable
          title="Top owners"
          icon={<Users className="h-4 w-4 text-info" />}
          rows={data.top_owners}
          emptyLabel="No owner data."
        />
        <SegmentTable
          title="Top bid types"
          icon={<FileText className="h-4 w-4 text-info" />}
          rows={data.top_bid_types}
          emptyLabel="No bid type data."
        />
        <SegmentTable
          title="Top counties"
          icon={<MapPin className="h-4 w-4 text-info" />}
          rows={data.top_counties}
          emptyLabel="No county data."
        />
      </section>

      {/* Top states + Competitor frequency */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <SegmentTable
          title="Top states"
          icon={<Map className="h-4 w-4 text-info" />}
          rows={data.top_states}
          emptyLabel="No state data."
          mono
        />
        <div>
          <h3 className="text-sm font-semibold">Competitor frequency</h3>
          <p className="mb-3 text-xs text-muted-foreground">
            Line items where each competitor surfaces — top 10.
          </p>
          {competitorChart.length === 0 ? (
            <p className="text-xs text-muted-foreground">No competitor data.</p>
          ) : (
            <div
              className="w-full"
              style={{
                height: `${Math.max(160, competitorChart.length * 28)}px`,
              }}
            >
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={competitorChart}
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
                    width={140}
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
                  <Bar
                    dataKey="value"
                    radius={[0, 6, 6, 0]}
                    fill={toneStyles.warn.fill}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </section>

      {/* Fee statistics */}
      <section className="rounded-lg border border-border bg-card p-4">
        <div className="mb-3 flex items-center gap-2">
          <CircleDollarSign className="h-4 w-4 text-info" />
          <h4 className="text-sm font-semibold">Fee statistics</h4>
        </div>
        {data.fee_statistics.length === 0 ? (
          <p className="text-xs text-muted-foreground">No fee data.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th className="py-2 font-medium">Fee</th>
                  <th className="py-2 text-right font-medium">Count</th>
                  <th className="py-2 text-right font-medium">Min</th>
                  <th className="py-2 text-right font-medium">Avg</th>
                  <th className="py-2 text-right font-medium">Max</th>
                </tr>
              </thead>
              <tbody>
                {data.fee_statistics.map((f) => (
                  <tr key={f.fee} className="border-b border-border/50">
                    <td className="py-2">
                      <span className="font-medium">
                        {FEE_LABELS[f.fee] ?? humanizeKey(f.fee)}
                      </span>
                    </td>
                    <td className="py-2 text-right font-mono tabular-nums">
                      {f.count.toLocaleString()}
                    </td>
                    <td className="py-2 text-right font-mono tabular-nums">
                      {f.min_value === null ? "—" : formatMoney(f.min_value)}
                    </td>
                    <td className="py-2 text-right font-mono tabular-nums">
                      {f.avg_value === null ? "—" : formatMoney(f.avg_value)}
                    </td>
                    <td className="py-2 text-right font-mono tabular-nums">
                      {f.max_value === null ? "—" : formatMoney(f.max_value)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
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
}: {
  title: string;
  subtitle: string;
  data: { key: string; label: string; value: number; tone: Tone }[];
}) {
  const total = data.reduce((acc, d) => acc + d.value, 0);
  return (
    <div>
      <h3 className="text-sm font-semibold">{title}</h3>
      <p className="mb-3 text-xs text-muted-foreground">
        {subtitle} {total.toLocaleString()} proposals classified.
      </p>
      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
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

function SegmentTable({
  title,
  icon,
  rows,
  emptyLabel,
  mono = false,
}: {
  title: string;
  icon: React.ReactNode;
  rows: Array<{ segment: string; count: number }>;
  emptyLabel: string;
  mono?: boolean;
}) {
  const max = rows.reduce((acc, r) => Math.max(acc, r.count), 0);
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center gap-2">
        {icon}
        <h4 className="text-sm font-semibold">{title}</h4>
      </div>
      {rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">{emptyLabel}</p>
      ) : (
        <div className="space-y-2">
          {rows.slice(0, 8).map((r) => {
            const pct = max > 0 ? (r.count / max) * 100 : 0;
            return (
              <div key={r.segment} className="space-y-1">
                <div className="flex items-center justify-between gap-3 text-xs">
                  <span
                    className={cn(
                      "min-w-0 flex-1 truncate font-medium",
                      mono && "font-mono",
                    )}
                    title={r.segment}
                  >
                    {r.segment}
                  </span>
                  <span className="font-mono tabular-nums">
                    {r.count.toLocaleString()}
                  </span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full"
                    style={{
                      width: `${Math.min(100, pct)}%`,
                      background: toneStyles.info.fill,
                    }}
                  />
                </div>
              </div>
            );
          })}
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
          AI-generated next actions for the proposal pipeline.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="rounded-lg border border-dashed border-border bg-muted/30 p-4 text-center">
          <p className="text-sm font-medium">Coming in Phase 6</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Claude will surface owners worth deeper outreach, flag
            bid-type categories where competitor density warrants
            scrutiny, and recommend geography expansions based on the
            in-state vs. out-of-state mix — directly in this panel.
          </p>
          <div className="mt-3 flex justify-center">
            <FileText className="h-6 w-6 text-muted-foreground/50" />
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

function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1)}…`;
}

function humanizeKey(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
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
