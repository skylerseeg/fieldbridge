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
  AlertOctagon,
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Banknote,
  Bell,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  Clock,
  FileText,
  Gavel,
  Info,
  ListChecks,
  Settings,
  Shield,
  Sparkles,
  Truck,
  XCircle,
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
  dismissRecommendation,
  fetchRecommendationsInsights,
  fetchRecommendationsList,
  fetchRecommendationsSummary,
  markRecommendationDone,
  snoozeRecommendation,
  type ListParams,
  type Priority,
  type RecCategory,
  type RecStatus,
  type RecommendationListResponse,
  type RecommendationListRow,
  type SortDir,
  type SortField,
} from "./recommendations-api";

/**
 * Recommendations module — Phase 5 page.
 *
 * Layout:
 *   ┌── 4 KPI tiles (triage) ──────────────────────────┐ ┌── Recommendations
 *   │  Open · P1 critical · Impact $ · Avg age         │ │   (right rail)
 *   ├── Tabs: Overview · List · Insights ──────────────┤ │
 *   │  Overview: priority mix bar + status / money     │ │
 *   │            / aging summary                       │ │
 *   │  List:     paginated TanStack table with         │ │
 *   │            row-level dismiss/snooze/done         │ │
 *   │            mutations (optimistic updates)        │ │
 *   │  Insights: priority + status + category mix,     │ │
 *   │            aging chart, top sources, category    │ │
 *   │            impact, top by impact, recent         │ │
 *   │            resolutions                           │ │
 *   └──────────────────────────────────────────────────┘ └──────────────────
 *
 * One row per AI-surfaced recommendation. Three orthogonal axes:
 *   - **Priority** (p1 / p2 / p3) — drives crit / warn / info tone.
 *   - **Category** (financial / fleet / safety / operations / bids /
 *     proposals) — domain bucket, drives icon mapping.
 *   - **Status** (open / snoozed / dismissed / done) — workflow state.
 *
 * Severity → token mapping (no new colors):
 *   primary  = good / dominant healthy bucket (clean queue)
 *   info     = neutral fact (counts, p3, in-progress)
 *   warning  = caution (p2, mid-aged, snoozed)
 *   critical = alert (p1, stale, large impact)
 *
 * Mutations (`dismiss`, `snooze`, `mark_done`) flip only the row's
 * `status` field, so optimistic updates are safe — `onMutate` cancels
 * outstanding list queries, snapshots the cache, writes the predicted
 * status, and `onError` rolls back. `onSettled` invalidates the
 * entire `recommendations` key tree so summary tiles + insights re-
 * sync after the server confirms.
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

const priorityStyles: Record<
  Priority,
  { tone: Tone; label: string; Icon: typeof AlertOctagon }
> = {
  p1: { tone: "crit", label: "P1", Icon: AlertOctagon },
  p2: { tone: "warn", label: "P2", Icon: AlertTriangle },
  p3: { tone: "info", label: "P3", Icon: Info },
};

const categoryStyles: Record<
  RecCategory,
  { tone: Tone; label: string; Icon: typeof Banknote }
> = {
  financial: { tone: "info", label: "Financial", Icon: Banknote },
  fleet: { tone: "info", label: "Fleet", Icon: Truck },
  safety: { tone: "crit", label: "Safety", Icon: Shield },
  operations: { tone: "warn", label: "Operations", Icon: Settings },
  bids: { tone: "info", label: "Bids", Icon: Gavel },
  proposals: { tone: "info", label: "Proposals", Icon: FileText },
};

const statusStyles: Record<
  RecStatus,
  { tone: Tone; label: string }
> = {
  open: { tone: "info", label: "Open" },
  snoozed: { tone: "warn", label: "Snoozed" },
  dismissed: { tone: "neutral", label: "Dismissed" },
  done: { tone: "good", label: "Done" },
};

// Display order for stacks.
const PRIORITY_ORDER: Priority[] = ["p1", "p2", "p3"];
const STATUS_ORDER: RecStatus[] = ["open", "snoozed", "dismissed", "done"];
const CATEGORY_ORDER: RecCategory[] = [
  "financial",
  "fleet",
  "safety",
  "operations",
  "bids",
  "proposals",
];

// Default snooze period for the row-level "Snooze" button.
const DEFAULT_SNOOZE_DAYS = 7;

// Query key factory.
const keys = {
  all: ["recommendations"] as const,
  summary: () => [...keys.all, "summary"] as const,
  list: (params: ListParams) => [...keys.all, "list", params] as const,
  insights: (topN: number) => [...keys.all, "insights", topN] as const,
};

// ──────────────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────────────

export function RecommendationsPage() {
  return (
    <div className="p-6 lg:p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">
          Recommendations
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          AI-surfaced actions across modules — prioritized P1/P2/P3 with
          dollar impact, owner, and a recommended next step.
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
    queryFn: fetchRecommendationsSummary,
  });

  // Four triage-oriented tiles. Severity adapts:
  //   - Open: 0 = good · ≤10 = info · ≤25 = warn · else crit.
  //   - P1 critical: 0 = good · ≤2 = info · ≤5 = warn · else crit.
  //   - Potential impact: info / neutral.
  //   - Avg age: ≤7 = good · ≤14 = info · ≤30 = warn · else crit.
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

    const p1Tone: Tone =
      data.open_p1_count === 0
        ? "good"
        : data.open_p1_count <= 2
          ? "info"
          : data.open_p1_count <= 5
            ? "warn"
            : "crit";

    const ageTone: Tone =
      data.average_age_days === null
        ? "neutral"
        : data.average_age_days <= 7
          ? "good"
          : data.average_age_days <= 14
            ? "info"
            : data.average_age_days <= 30
              ? "warn"
              : "crit";

    return [
      {
        key: "open",
        tone: openTone,
        Icon: ListChecks,
        value: data.open_count.toLocaleString(),
        label: "Open",
        sub: `${data.total_recommendations.toLocaleString()} total · ${data.snoozed_count.toLocaleString()} snoozed`,
      },
      {
        key: "p1",
        tone: p1Tone,
        Icon: AlertOctagon,
        value: data.open_p1_count.toLocaleString(),
        label: "P1 critical",
        sub:
          data.p1_count > 0
            ? `${data.p1_count.toLocaleString()} P1 lifetime`
            : "no P1 history",
      },
      {
        key: "impact",
        tone:
          data.total_potential_impact > 0
            ? ("info" as Tone)
            : ("neutral" as Tone),
        Icon: CircleDollarSign,
        value:
          data.total_potential_impact > 0
            ? formatMoney(data.total_potential_impact)
            : "—",
        label: "Potential impact",
        sub: data.total_potential_impact > 0 ? "across open" : "no impact data",
      },
      {
        key: "age",
        tone: ageTone,
        Icon: Clock,
        value:
          data.average_age_days === null
            ? "—"
            : `${data.average_age_days.toFixed(0)}d`,
        label: "Avg age",
        sub:
          data.oldest_open_age_days !== null
            ? `oldest ${data.oldest_open_age_days.toFixed(0)}d`
            : "no open items",
      },
    ];
  }, [data]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Triage snapshot</CardTitle>
          <CardDescription>
            Cross-module rollup · pulled from the recommendations queue
          </CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          {data && (
            <>
              <Badge variant="mono">
                {data.distinct_categories.toLocaleString()} categories
              </Badge>
              <Badge variant="mono">
                {data.distinct_sources.toLocaleString()} sources
              </Badge>
              <Badge variant="mono">
                {data.done_count.toLocaleString()} resolved
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
    queryFn: fetchRecommendationsSummary,
  });
  const insights = useQuery({
    queryKey: keys.insights(10),
    queryFn: () => fetchRecommendationsInsights(10),
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

  // Headline: priority mix.
  const priorityChart = PRIORITY_ORDER.map((k) => ({
    key: k,
    label: priorityStyles[k].label,
    value: i.priority_breakdown[k],
    tone: priorityStyles[k].tone,
  }));

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
      <div className="md:col-span-2">
        <h3 className="text-sm font-semibold">Priority mix</h3>
        <p className="mb-3 text-xs text-muted-foreground">
          Lifetime distribution across {s.total_recommendations.toLocaleString()}{" "}
          recommendations.
        </p>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={priorityChart}
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
                {priorityChart.map((d) => (
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
          sub={shareSub(s.open_count, s.total_recommendations)}
        />
        <SummaryRow
          label="Snoozed"
          value={s.snoozed_count.toLocaleString()}
          sub={shareSub(s.snoozed_count, s.total_recommendations)}
        />
        <SummaryRow
          label="Done"
          value={s.done_count.toLocaleString()}
          sub={shareSub(s.done_count, s.total_recommendations)}
        />
        <SummaryRow
          label="Dismissed"
          value={s.dismissed_count.toLocaleString()}
          sub={shareSub(s.dismissed_count, s.total_recommendations)}
        />
        <div className="border-t border-border pt-3" />
        <h3 className="text-sm font-semibold">Money</h3>
        <SummaryRow
          label="Potential impact"
          value={
            s.total_potential_impact > 0
              ? formatMoney(s.total_potential_impact)
              : "—"
          }
          sub={s.total_potential_impact > 0 ? "across open" : undefined}
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
  const [priority, setPriority] = useState<Priority | "all">("all");
  const [category, setCategory] = useState<RecCategory | "all">("all");
  const [status, setStatus] = useState<RecStatus | "all">("open");
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
      ...(priority !== "all" ? { priority } : {}),
      ...(category !== "all" ? { category } : {}),
      ...(status !== "all" ? { status } : {}),
    }),
    [page, pageSize, sortBy, sortDir, search, priority, category, status],
  );

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: keys.list(params),
    queryFn: () => fetchRecommendationsList(params),
    placeholderData: keepPreviousData,
  });

  const actions = useRecommendationActions(params);

  const columns = useMemo<ColumnDef<RecommendationListRow>[]>(
    () => [
      {
        accessorKey: "title",
        header: "Recommendation",
        cell: ({ row }) => {
          const c = categoryStyles[row.original.category];
          return (
            <div className="flex flex-col gap-0.5">
              <span
                className="line-clamp-2 text-xs font-medium"
                title={row.original.title}
              >
                {row.original.title}
              </span>
              {row.original.summary && (
                <span
                  className="line-clamp-2 text-[11px] text-muted-foreground"
                  title={row.original.summary}
                >
                  {row.original.summary}
                </span>
              )}
              <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-muted-foreground">
                <c.Icon className="h-3 w-3" />
                <span>{c.label}</span>
                {row.original.source && (
                  <>
                    <span>·</span>
                    <span className="font-mono">{row.original.source}</span>
                  </>
                )}
              </div>
            </div>
          );
        },
      },
      {
        accessorKey: "priority",
        header: "Priority",
        cell: ({ row }) => {
          const p = priorityStyles[row.original.priority];
          const ts = toneStyles[p.tone];
          return (
            <span
              className={cn(
                "inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
                ts.bg,
                ts.text,
              )}
            >
              <p.Icon className="h-3 w-3" />
              {p.label}
            </span>
          );
        },
      },
      {
        accessorKey: "impact_dollars",
        header: "Impact",
        cell: ({ row }) =>
          row.original.impact_dollars === null ||
          row.original.impact_dollars === 0 ? (
            <span className="text-xs text-muted-foreground">—</span>
          ) : (
            <span className="font-mono text-xs tabular-nums">
              {formatMoney(row.original.impact_dollars)}
            </span>
          ),
      },
      {
        accessorKey: "created_at",
        header: "Age",
        cell: ({ row }) => {
          const r = row.original;
          return (
            <div className="flex flex-col gap-0.5">
              <span className="font-mono text-xs tabular-nums">
                {r.age_days.toFixed(0)}d
              </span>
              {r.status === "snoozed" && r.snoozed_until && (
                <span className="text-[10px] text-warning">
                  until {formatDate(r.snoozed_until)}
                </span>
              )}
            </div>
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
            actions.dismiss.isPending ||
            actions.snooze.isPending ||
            actions.done.isPending;
          // Resolved rows can't be re-acted on from the table.
          if (r.status === "done" || r.status === "dismissed") {
            return (
              <span className="text-[11px] text-muted-foreground">
                {r.status === "done" ? "resolved" : "dismissed"}
              </span>
            );
          }
          return (
            <div className="flex items-center gap-1">
              <Button
                variant="outline"
                size="sm"
                disabled={isPending}
                onClick={() => actions.done.mutate({ id: r.id })}
                title="Mark done"
              >
                <CheckCircle2 className="h-3 w-3" />
                <span className="ml-1 hidden sm:inline">Done</span>
              </Button>
              {r.status === "open" && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={isPending}
                  onClick={() =>
                    actions.snooze.mutate({
                      id: r.id,
                      until: snoozeUntil(DEFAULT_SNOOZE_DAYS),
                    })
                  }
                  title={`Snooze ${DEFAULT_SNOOZE_DAYS}d`}
                >
                  <Bell className="h-3 w-3" />
                  <span className="ml-1 hidden sm:inline">
                    {DEFAULT_SNOOZE_DAYS}d
                  </span>
                </Button>
              )}
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
          placeholder="Search title, action, owner…"
          className="w-full sm:w-72"
        />
        <Select<Priority | "all">
          value={priority}
          onChange={(v) => {
            setPriority(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All priorities" },
            { value: "p1", label: "P1 critical" },
            { value: "p2", label: "P2 high" },
            { value: "p3", label: "P3 medium" },
          ]}
        />
        <Select<RecCategory | "all">
          value={category}
          onChange={(v) => {
            setCategory(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All categories" },
            { value: "financial", label: "Financial" },
            { value: "fleet", label: "Fleet" },
            { value: "safety", label: "Safety" },
            { value: "operations", label: "Operations" },
            { value: "bids", label: "Bids" },
            { value: "proposals", label: "Proposals" },
          ]}
        />
        <Select<RecStatus | "all">
          value={status}
          onChange={(v) => {
            setStatus(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All statuses" },
            { value: "open", label: "Open" },
            { value: "snoozed", label: "Snoozed" },
            { value: "done", label: "Done" },
            { value: "dismissed", label: "Dismissed" },
          ]}
        />
        {isFetching && (
          <span className="text-[11px] text-muted-foreground">refreshing…</span>
        )}
      </div>

      {isError && <ErrorBlock message="Couldn't load recommendations." />}
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
                  No recommendations match the current filters.
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
// Mutation hook — dismiss / snooze / done with optimistic updates.
//
// Each action only flips the row's `status` (and optionally
// `snoozed_until`). That's a closed write, so we can safely apply the
// predicted state into the list cache immediately, then roll back on
// error and re-sync on settled.
// ──────────────────────────────────────────────────────────────────────

interface ActionContext {
  previousList: RecommendationListResponse | undefined;
}

function useRecommendationActions(params: ListParams) {
  const queryClient = useQueryClient();
  const listKey = keys.list(params);

  function applyStatus(
    id: string,
    nextStatus: RecStatus,
    snoozedUntil: string | null = null,
  ): ActionContext {
    queryClient.cancelQueries({ queryKey: keys.all }).catch(() => {});
    const previousList =
      queryClient.getQueryData<RecommendationListResponse>(listKey);
    if (previousList) {
      queryClient.setQueryData<RecommendationListResponse>(listKey, {
        ...previousList,
        items: previousList.items.map((row) =>
          row.id === id
            ? {
                ...row,
                status: nextStatus,
                snoozed_until:
                  nextStatus === "snoozed" ? snoozedUntil : null,
              }
            : row,
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

  const dismiss = useMutation<
    unknown,
    Error,
    { id: string; reason?: string },
    ActionContext
  >({
    mutationFn: ({ id, reason }) => dismissRecommendation(id, { reason }),
    onMutate: ({ id }) => applyStatus(id, "dismissed"),
    onError: (_err, _vars, ctx) => rollback(ctx),
    onSettled: settle,
  });

  const snooze = useMutation<
    unknown,
    Error,
    { id: string; until: string; reason?: string },
    ActionContext
  >({
    mutationFn: ({ id, until, reason }) =>
      snoozeRecommendation(id, { until, reason }),
    onMutate: ({ id, until }) => applyStatus(id, "snoozed", until),
    onError: (_err, _vars, ctx) => rollback(ctx),
    onSettled: settle,
  });

  const done = useMutation<
    unknown,
    Error,
    { id: string; note?: string },
    ActionContext
  >({
    mutationFn: ({ id, note }) => markRecommendationDone(id, { note }),
    onMutate: ({ id }) => applyStatus(id, "done"),
    onError: (_err, _vars, ctx) => rollback(ctx),
    onSettled: settle,
  });

  const error =
    dismiss.error?.message ??
    snooze.error?.message ??
    done.error?.message ??
    null;

  return { dismiss, snooze, done, error };
}

// ── Insights ─────────────────────────────────────────────────────────

function InsightsTab() {
  const { data, isLoading, isError } = useQuery({
    queryKey: keys.insights(10),
    queryFn: () => fetchRecommendationsInsights(10),
  });

  if (isError) return <ErrorBlock message="Couldn't load insights." />;
  if (isLoading || !data) return <SkeletonBlock height="h-64" />;

  const priorityChart = PRIORITY_ORDER.map((k) => ({
    key: k,
    label: priorityStyles[k].label,
    value: data.priority_breakdown[k],
    tone: priorityStyles[k].tone,
  }));

  const statusChart = STATUS_ORDER.map((k) => ({
    key: k,
    label: statusStyles[k].label,
    value: data.status_breakdown[k],
    tone: statusStyles[k].tone,
  }));

  const categoryChart = CATEGORY_ORDER.map((k) => ({
    key: k,
    label: categoryStyles[k].label,
    value: data.category_breakdown[k],
    tone: categoryStyles[k].tone,
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

  return (
    <div className="space-y-6">
      {/* Priority + Status breakdowns */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <BreakdownChart
          title="Priority"
          subtitle="Lifetime distribution across recommendations."
          data={priorityChart}
          unitLabel="recommendations"
        />
        <BreakdownChart
          title="Status"
          subtitle="Where every recommendation stands today."
          data={statusChart}
          unitLabel="recommendations"
        />
      </section>

      {/* Category + Aging */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div>
          <h3 className="text-sm font-semibold">Category</h3>
          <p className="mb-3 text-xs text-muted-foreground">
            Recommendations grouped by domain bucket.
          </p>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={categoryChart}
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
                  {categoryChart.map((d) => (
                    <Cell key={d.key} fill={toneStyles[d.tone].fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <BreakdownChart
          title="Aging (open queue)"
          subtitle="How long open recommendations have been sitting."
          data={agingChart}
          unitLabel="open"
        />
      </section>

      {/* Top sources + Category impact */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <SegmentTable
          title="Top sources"
          icon={<ListChecks className="h-4 w-4 text-info" />}
          rows={data.top_sources}
          emptyLabel="No source data."
          mono
        />
        <div>
          <h3 className="text-sm font-semibold">Open impact by category</h3>
          <p className="mb-3 text-xs text-muted-foreground">
            Sum of open-recommendation impact $ within each category.
          </p>
          {data.category_impact.length === 0 ? (
            <p className="text-xs text-muted-foreground">No impact data.</p>
          ) : (
            <div className="space-y-2">
              {data.category_impact.map((c) => {
                const cs = categoryStyles[c.category];
                const ts = toneStyles[cs.tone];
                const max = data.category_impact.reduce(
                  (acc, r) => Math.max(acc, r.total_impact),
                  0,
                );
                const pct = max > 0 ? (c.total_impact / max) * 100 : 0;
                return (
                  <div key={c.category} className="space-y-1">
                    <div className="flex items-center justify-between gap-3 text-xs">
                      <span className="inline-flex items-center gap-1.5 font-medium">
                        <cs.Icon className={cn("h-3.5 w-3.5", ts.text)} />
                        {cs.label}
                      </span>
                      <span className="font-mono tabular-nums">
                        {formatMoney(c.total_impact)}{" "}
                        <span className="ml-1 text-muted-foreground">
                          {c.open_count} open
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

      {/* Top by impact + Recent resolutions */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="mb-3 flex items-center gap-2">
            <CircleDollarSign className="h-4 w-4 text-info" />
            <h4 className="text-sm font-semibold">Top by impact</h4>
          </div>
          {data.top_by_impact.length === 0 ? (
            <p className="text-xs text-muted-foreground">No data.</p>
          ) : (
            <div className="space-y-1.5">
              {data.top_by_impact.slice(0, 8).map((r) => {
                const p = priorityStyles[r.priority];
                const c = categoryStyles[r.category];
                return (
                  <div
                    key={r.id}
                    className="flex items-center justify-between gap-3 text-xs"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium" title={r.title}>
                        {r.title}
                      </div>
                      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                        <c.Icon className="h-3 w-3" />
                        {c.label}
                        <span>·</span>
                        <span className="font-mono">{r.source}</span>
                        <span>·</span>
                        <span>{r.age_days.toFixed(0)}d</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
                          toneStyles[p.tone].bg,
                          toneStyles[p.tone].text,
                        )}
                      >
                        {p.label}
                      </span>
                      <span className="font-mono text-xs tabular-nums">
                        {r.impact_dollars === null
                          ? "—"
                          : formatMoney(r.impact_dollars)}
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
            <CheckCircle2 className="h-4 w-4 text-primary" />
            <h4 className="text-sm font-semibold">Recent resolutions</h4>
          </div>
          {data.recent_resolutions.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No resolutions yet — clean queue.
            </p>
          ) : (
            <div className="space-y-1.5">
              {data.recent_resolutions.slice(0, 8).map((r) => {
                const c = categoryStyles[r.category];
                const st = statusStyles[r.status];
                return (
                  <div
                    key={r.id}
                    className="flex items-center justify-between gap-3 text-xs"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium" title={r.title}>
                        {r.title}
                      </div>
                      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                        <c.Icon className="h-3 w-3" />
                        {c.label}
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
        </div>
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
          <CardTitle>Conversational triage</CardTitle>
        </div>
        <CardDescription>
          Drill into a recommendation and ask Claude follow-up questions.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="rounded-lg border border-dashed border-border bg-muted/30 p-4 text-center">
          <p className="text-sm font-medium">Coming in Phase 6</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Select a row and Claude will explain why it surfaced, walk
            through the supporting evidence, and propose a step-by-step
            plan to resolve it — directly in this panel.
          </p>
          <div className="mt-3 flex justify-center">
            <Sparkles className="h-6 w-6 text-muted-foreground/50" />
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

// ISO date string `N` days from now.
function snoozeUntil(days: number): string {
  const ms = Date.now() + days * 24 * 60 * 60 * 1000;
  return new Date(ms).toISOString();
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
