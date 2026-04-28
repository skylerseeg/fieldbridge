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
  ArrowUpRight,
  Award,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  Flag,
  Gavel,
  HelpCircle,
  MinusCircle,
  Sparkles,
  Target,
  TrendingUp,
  Trophy,
  Users,
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
  fetchBidsInsights,
  fetchBidsList,
  fetchBidsSummary,
  type BidListRow,
  type BidOutcome,
  type CompetitionTier,
  type ListParams,
  type MarginTier,
  type SortDir,
  type SortField,
} from "./bids-api";

/**
 * Bids module — Phase 5 page.
 *
 * Layout:
 *   ┌── 4 KPI tiles (bid pipeline) ────────────────────┐ ┌── Recommendations
 *   │  Total bids · Win rate · Won $ · Pipeline        │ │   (right rail)
 *   ├── Tabs: Overview · List · Insights ──────────────┤ │
 *   │  Overview: outcome mix bar + activity totals     │ │
 *   │  List:     paginated TanStack table              │ │
 *   │  Insights: margin/competition mix, win-rate by   │ │
 *   │            segment, near misses, big wins, risk  │ │
 *   └──────────────────────────────────────────────────┘ └──────────────────
 *
 * One entity per **(job, bid_date) pair**. Three orthogonal axes:
 *   - outcome (won / lost / no_bid / unknown)
 *   - margin tier (winner / close / moderate / wide / unknown) — pricing miss
 *   - competition tier (solo / light / typical / crowded / unknown)
 *
 * Severity → token mapping (no new colors):
 *   primary  = won / winner margin / healthy
 *   info     = neutral fact (counts, light/typical competition)
 *   warning  = caution (close/moderate margin, crowded competition)
 *   critical = alert (wide margin loss, big lost-by)
 *
 * Mutations: bids endpoints are read-only. The query-key factory is
 * ready for Phase 6 (e.g. flagging an outlook bid for review).
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

const outcomeStyles: Record<
  BidOutcome,
  { tone: Tone; label: string; Icon: typeof Trophy }
> = {
  won: { tone: "good", label: "Won", Icon: Trophy },
  lost: { tone: "warn", label: "Lost", Icon: XCircle },
  no_bid: { tone: "neutral", label: "No bid", Icon: MinusCircle },
  unknown: { tone: "neutral", label: "Unknown", Icon: HelpCircle },
};

const marginStyles: Record<
  MarginTier,
  { tone: Tone; label: string; Icon: typeof Trophy }
> = {
  winner: { tone: "good", label: "Winner", Icon: Trophy },
  close: { tone: "warn", label: "Close", Icon: Target },
  moderate: { tone: "warn", label: "Moderate", Icon: ArrowUpRight },
  wide: { tone: "crit", label: "Wide", Icon: ArrowUpRight },
  unknown: { tone: "neutral", label: "Unknown", Icon: HelpCircle },
};

const competitionStyles: Record<
  CompetitionTier,
  { tone: Tone; label: string; Icon: typeof Users }
> = {
  solo: { tone: "good", label: "Solo", Icon: Users },
  light: { tone: "info", label: "Light", Icon: Users },
  typical: { tone: "info", label: "Typical", Icon: Users },
  crowded: { tone: "warn", label: "Crowded", Icon: Users },
  unknown: { tone: "neutral", label: "Unknown", Icon: HelpCircle },
};

// Display order for outcome / margin / competition stacks.
const OUTCOME_ORDER: BidOutcome[] = ["won", "lost", "no_bid", "unknown"];
const MARGIN_ORDER: MarginTier[] = [
  "winner",
  "close",
  "moderate",
  "wide",
  "unknown",
];
const COMPETITION_ORDER: CompetitionTier[] = [
  "solo",
  "light",
  "typical",
  "crowded",
  "unknown",
];

// Query key factory.
const keys = {
  all: ["bids"] as const,
  summary: () => [...keys.all, "summary"] as const,
  list: (params: ListParams) => [...keys.all, "list", params] as const,
  insights: (topN: number) => [...keys.all, "insights", topN] as const,
};

// ──────────────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────────────

export function BidsPage() {
  return (
    <div className="p-6 lg:p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Bids</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Bid history with win rate, margin tier vs. low bid, and bidder
          density across owners, counties, and estimators.
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
    queryFn: fetchBidsSummary,
  });

  // Four bid-pipeline tiles. Severity adapts:
  //   - Win rate: ≥35% good, ≥20% info, ≥10% warn, else crit.
  //     (Backend returns win_rate as a fraction in [0, 1].)
  //   - Won $: good when nonzero, neutral when zero (no awards yet).
  //   - Pipeline: info if rows exist, neutral when empty.
  const tiles = useMemo(() => {
    if (!data) return [];

    const winRate = data.win_rate;
    const winRateTone: Tone =
      data.bids_submitted === 0
        ? "neutral"
        : winRate >= 0.35
          ? "good"
          : winRate >= 0.2
            ? "info"
            : winRate >= 0.1
              ? "warn"
              : "crit";

    const wonTone: Tone =
      data.total_vancon_won_amount > 0 ? "good" : "neutral";

    const pipelineTone: Tone = data.outlook_count > 0 ? "info" : "neutral";

    return [
      {
        key: "total",
        tone: "info" as Tone,
        Icon: Gavel,
        value: data.total_bids.toLocaleString(),
        label: "Total bids",
        sub: `${data.bids_submitted.toLocaleString()} submitted · ${data.no_bids.toLocaleString()} no-bid`,
      },
      {
        key: "win_rate",
        tone: winRateTone,
        Icon: Trophy,
        value:
          data.bids_submitted === 0 ? "—" : `${(winRate * 100).toFixed(1)}%`,
        label: "Win rate",
        sub:
          data.bids_submitted === 0
            ? "no submissions"
            : `${data.bids_won.toLocaleString()} won / ${data.bids_lost.toLocaleString()} lost`,
      },
      {
        key: "won_dollars",
        tone: wonTone,
        Icon: Award,
        value: formatMoney(data.total_vancon_won_amount),
        label: "Won $ value",
        sub: `${formatMoney(data.total_vancon_bid_amount)} submitted`,
      },
      {
        key: "pipeline",
        tone: pipelineTone,
        Icon: Target,
        value: data.outlook_count.toLocaleString(),
        label: "Pipeline",
        sub: `${data.distinct_estimators} estimators · ${data.distinct_owners} owners`,
      },
    ];
  }, [data]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Bid book</CardTitle>
          <CardDescription>
            Submitted + walked bids · pulled from the bid-history mart
          </CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          {data && (
            <>
              <Badge variant="mono">
                {data.distinct_bid_types} bid types
              </Badge>
              <Badge variant="mono">
                {data.distinct_counties} counties
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
    queryFn: fetchBidsSummary,
  });
  const insights = useQuery({
    queryKey: keys.insights(10),
    queryFn: () => fetchBidsInsights(10),
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

  // Headline visualization: outcome mix (won / lost / no_bid / unknown)
  // — authoritative counts from the insights breakdown.
  const outcomeChart = OUTCOME_ORDER.map((k) => ({
    key: k,
    label: outcomeStyles[k].label,
    value: ins.outcome_breakdown[k],
    tone: outcomeStyles[k].tone,
  }));

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
      <div className="md:col-span-2">
        <h3 className="text-sm font-semibold">Outcome mix</h3>
        <p className="mb-3 text-xs text-muted-foreground">
          How {s.total_bids.toLocaleString()} historical bids landed across
          win, loss, walked, and unscored buckets.
        </p>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={outcomeChart}
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
                {outcomeChart.map((d) => (
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
          label="Total bids"
          value={s.total_bids.toLocaleString()}
        />
        <SummaryRow
          label="Submitted"
          value={s.bids_submitted.toLocaleString()}
        />
        <SummaryRow label="Walked" value={s.no_bids.toLocaleString()} />
        <div className="border-t border-border pt-3" />
        <h3 className="text-sm font-semibold">Outcomes</h3>
        <SummaryRow
          label="Won"
          value={s.bids_won.toLocaleString()}
          sub={
            s.bids_submitted > 0
              ? `${(s.win_rate * 100).toFixed(1)}% win rate`
              : undefined
          }
        />
        <SummaryRow label="Lost" value={s.bids_lost.toLocaleString()} />
        {s.unknown_outcome > 0 && (
          <SummaryRow
            label="Unscored"
            value={s.unknown_outcome.toLocaleString()}
          />
        )}
        <SummaryRow
          label="Median bidders"
          value={
            s.median_number_bidders == null
              ? "—"
              : s.median_number_bidders.toFixed(1)
          }
        />
        <div className="border-t border-border pt-3" />
        <h3 className="text-sm font-semibold">Money</h3>
        <SummaryRow
          label="Won $ value"
          value={formatMoney(s.total_vancon_won_amount)}
        />
        <SummaryRow
          label="Submitted $"
          value={formatMoney(s.total_vancon_bid_amount)}
          sub={
            s.bids_submitted > 0
              ? `avg ${formatMoney(s.avg_vancon_bid)}`
              : undefined
          }
        />
        <SummaryRow
          label="Pipeline"
          value={s.outlook_count.toLocaleString()}
          sub="upcoming"
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
  const [outcome, setOutcome] = useState<BidOutcome | "all">("all");
  const [margin, setMargin] = useState<MarginTier | "all">("all");
  const [competition, setCompetition] = useState<CompetitionTier | "all">(
    "all",
  );
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [sorting, setSorting] = useState<SortingState>([
    { id: "bid_date", desc: true },
  ]);

  const sortBy = (sorting[0]?.id ?? "bid_date") as SortField;
  const sortDir: SortDir = sorting[0]?.desc ? "desc" : "asc";

  const params: ListParams = useMemo(
    () => ({
      page,
      page_size: pageSize,
      sort_by: sortBy,
      sort_dir: sortDir,
      ...(search.trim() ? { search: search.trim() } : {}),
      ...(outcome !== "all" ? { outcome } : {}),
      ...(margin !== "all" ? { margin_tier: margin } : {}),
      ...(competition !== "all" ? { competition_tier: competition } : {}),
    }),
    [page, pageSize, sortBy, sortDir, search, outcome, margin, competition],
  );

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: keys.list(params),
    queryFn: () => fetchBidsList(params),
    placeholderData: keepPreviousData,
  });

  const columns = useMemo<ColumnDef<BidListRow>[]>(
    () => [
      {
        accessorKey: "job",
        header: "Job",
        cell: ({ row }) => (
          <div className="flex flex-col gap-0.5">
            <span className="font-mono font-medium">{row.original.job}</span>
            <span className="text-[11px] text-muted-foreground">
              {formatDate(row.original.bid_date)}
              {row.original.county && ` · ${row.original.county}`}
            </span>
          </div>
        ),
      },
      {
        accessorKey: "owner",
        header: "Owner",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex flex-col gap-0.5">
            <span className="text-sm">{row.original.owner ?? "—"}</span>
            {(row.original.bid_type || row.original.estimator) && (
              <span className="text-[11px] text-muted-foreground">
                {[row.original.bid_type, row.original.estimator]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            )}
          </div>
        ),
      },
      {
        accessorKey: "vancon",
        header: "VanCon $",
        cell: ({ row }) => {
          const v = row.original.vancon;
          if (v == null) {
            if (!row.original.was_bid) {
              return (
                <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
                  <MinusCircle className="h-3 w-3" />
                  walked
                </span>
              );
            }
            return <span className="text-xs text-muted-foreground">—</span>;
          }
          const low = row.original.low;
          return (
            <div className="flex flex-col gap-0.5">
              <span className="font-mono tabular-nums">{formatMoney(v)}</span>
              {low != null && (
                <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                  low {formatMoney(low)}
                </span>
              )}
            </div>
          );
        },
      },
      {
        id: "outcome",
        accessorKey: "outcome",
        header: "Outcome",
        enableSorting: false,
        cell: ({ row }) => {
          const o = outcomeStyles[row.original.outcome];
          const ts = toneStyles[o.tone];
          return (
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
                ts.bg,
                ts.text,
              )}
            >
              <o.Icon className="h-3 w-3" />
              {o.label}
            </span>
          );
        },
      },
      {
        id: "margin_tier",
        accessorKey: "percent_over",
        header: "Margin",
        cell: ({ row }) => {
          const pct = row.original.percent_over;
          const lostBy = row.original.lost_by;
          const m = marginStyles[row.original.margin_tier];
          const ts = toneStyles[m.tone];
          if (row.original.margin_tier === "winner") {
            return (
              <span
                className={cn(
                  "inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
                  ts.bg,
                  ts.text,
                )}
              >
                <Trophy className="h-3 w-3" />
                low bid
              </span>
            );
          }
          if (pct == null) {
            return <span className="text-xs text-muted-foreground">—</span>;
          }
          return (
            <div className="flex flex-col gap-0.5">
              <span
                className={cn(
                  "inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[11px] font-medium tabular-nums",
                  ts.bg,
                  ts.text,
                )}
              >
                <m.Icon className="h-3 w-3" />+{(pct * 100).toFixed(1)}%
              </span>
              {lostBy != null && lostBy > 0 && (
                <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                  −{formatMoney(lostBy)}
                </span>
              )}
            </div>
          );
        },
      },
      {
        accessorKey: "rank",
        header: "Rank",
        cell: ({ row }) => {
          const r = row.original.rank;
          const n = row.original.number_bidders;
          if (r == null && n == null) {
            return <span className="text-xs text-muted-foreground">—</span>;
          }
          return (
            <div className="flex flex-col gap-0.5">
              <span className="font-mono tabular-nums">
                {r != null ? `#${r}` : "—"}
                {n != null && (
                  <span className="text-muted-foreground"> / {n}</span>
                )}
              </span>
              <CompetitionChip tier={row.original.competition_tier} />
            </div>
          );
        },
      },
      {
        accessorKey: "number_bidders",
        header: "Bidders",
        cell: ({ row }) => {
          const n = row.original.number_bidders;
          if (n == null) {
            return <span className="text-xs text-muted-foreground">—</span>;
          }
          return (
            <span className="font-mono text-xs tabular-nums">{n}</span>
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
          placeholder="Search job, owner, estimator, county…"
          className="w-full sm:w-72"
        />
        <Select<BidOutcome | "all">
          value={outcome}
          onChange={(v) => {
            setOutcome(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All outcomes" },
            { value: "won", label: "Won" },
            { value: "lost", label: "Lost" },
            { value: "no_bid", label: "Walked" },
            { value: "unknown", label: "Unknown" },
          ]}
        />
        <Select<MarginTier | "all">
          value={margin}
          onChange={(v) => {
            setMargin(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All margin" },
            { value: "winner", label: "Winner" },
            { value: "close", label: "Close" },
            { value: "moderate", label: "Moderate" },
            { value: "wide", label: "Wide" },
            { value: "unknown", label: "Unknown" },
          ]}
        />
        <Select<CompetitionTier | "all">
          value={competition}
          onChange={(v) => {
            setCompetition(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All competition" },
            { value: "solo", label: "Solo" },
            { value: "light", label: "Light" },
            { value: "typical", label: "Typical" },
            { value: "crowded", label: "Crowded" },
            { value: "unknown", label: "Unknown" },
          ]}
        />
        {isFetching && (
          <span className="text-[11px] text-muted-foreground">refreshing…</span>
        )}
      </div>

      {isError && <ErrorBlock message="Couldn't load bids list." />}

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
                  No bids match the current filters.
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

function CompetitionChip({ tier }: { tier: CompetitionTier }) {
  const c = competitionStyles[tier];
  if (tier === "unknown") return null;
  const ts = toneStyles[c.tone];
  return (
    <span
      className={cn(
        "inline-flex w-fit items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium",
        ts.bg,
        ts.text,
      )}
    >
      {c.label.toLowerCase()}
    </span>
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
    queryFn: () => fetchBidsInsights(10),
  });

  if (isError) return <ErrorBlock message="Couldn't load insights." />;
  if (isLoading || !data) return <SkeletonBlock height="h-64" />;

  // Margin tier + Competition tier breakdown — both categorical mixes.
  const marginChart = MARGIN_ORDER.map((k) => ({
    key: k,
    label: marginStyles[k].label,
    value: data.margin_tier_breakdown[k],
    tone: marginStyles[k].tone,
  }));
  const competitionChart = COMPETITION_ORDER.map((k) => ({
    key: k,
    label: competitionStyles[k].label,
    value: data.competition_tier_breakdown[k],
    tone: competitionStyles[k].tone,
  }));

  const riskChart = data.risk_flag_frequency
    .filter((r) => r.count > 0)
    .map((r) => ({
      flag: humanizeFlag(r.flag),
      count: r.count,
      win_rate: r.win_rate * 100,
    }));

  return (
    <div className="space-y-6">
      {/* Margin + competition mix */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <BreakdownChart
          title="Margin tier vs. low bid"
          subtitle="How close VanCon came when submitting."
          data={marginChart}
        />
        <BreakdownChart
          title="Competition density"
          subtitle="Bidder count buckets across the book."
          data={competitionChart}
        />
      </section>

      {/* Win rate by segment */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <SegmentTable
          title="Win rate by bid type"
          rows={data.win_rate_by_bid_type}
        />
        <SegmentTable
          title="Win rate by estimator"
          rows={data.win_rate_by_estimator}
        />
        <SegmentTable
          title="Win rate by county"
          rows={data.win_rate_by_county}
        />
      </section>

      {/* Near misses + Big wins */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <NearMissTable rows={data.near_misses} />
        <BigWinTable rows={data.big_wins} />
      </section>

      {/* Risk flags */}
      {riskChart.length > 0 && (
        <section className="rounded-lg border border-border bg-card p-4">
          <div className="mb-3 flex items-center gap-2">
            <Flag className="h-4 w-4 text-warning" />
            <h4 className="text-sm font-semibold">Risk flag frequency</h4>
          </div>
          <p className="mb-3 text-xs text-muted-foreground">
            How often each risk flag appears, and the win rate among
            submitted bids carrying it.
          </p>
          <div
            className="w-full"
            style={{
              height: `${Math.max(96, riskChart.length * 32 + 32)}px`,
            }}
          >
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={riskChart}
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
                />
                <YAxis
                  type="category"
                  dataKey="flag"
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
                  formatter={(v: number, name: string) =>
                    name === "win_rate"
                      ? `${v.toFixed(1)}%`
                      : v.toLocaleString()
                  }
                />
                <Bar
                  dataKey="count"
                  name="bids"
                  radius={[0, 6, 6, 0]}
                  fill={toneStyles.warn.fill}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th className="py-2 font-medium">Flag</th>
                  <th className="py-2 text-right font-medium">Bids</th>
                  <th className="py-2 text-right font-medium">Win rate</th>
                </tr>
              </thead>
              <tbody>
                {data.risk_flag_frequency.map((r) => (
                  <tr key={r.flag} className="border-b border-border/50">
                    <td className="py-2 font-medium">{humanizeFlag(r.flag)}</td>
                    <td className="py-2 text-right font-mono tabular-nums">
                      {r.count.toLocaleString()}
                    </td>
                    <td className="py-2 text-right font-mono tabular-nums">
                      {r.count > 0 ? `${(r.win_rate * 100).toFixed(1)}%` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
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
        {subtitle} {total.toLocaleString()} bids classified.
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
  rows,
}: {
  title: string;
  rows: Array<{
    segment: string;
    submitted: number;
    won: number;
    win_rate: number;
    total_vancon_won_amount: number;
  }>;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center gap-2">
        <CircleDollarSign className="h-4 w-4 text-info" />
        <h4 className="text-sm font-semibold">{title}</h4>
      </div>
      {rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">No data.</p>
      ) : (
        <div className="space-y-1.5">
          {rows.slice(0, 6).map((r) => {
            const pct = r.win_rate * 100;
            const tone: Tone =
              r.submitted === 0
                ? "neutral"
                : pct >= 35
                  ? "good"
                  : pct >= 20
                    ? "info"
                    : pct >= 10
                      ? "warn"
                      : "crit";
            const ts = toneStyles[tone];
            return (
              <div
                key={r.segment}
                className="flex items-center justify-between gap-3 text-xs"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium" title={r.segment}>
                    {r.segment}
                  </div>
                  <div className="font-mono text-[11px] text-muted-foreground tabular-nums">
                    {r.won}/{r.submitted} won
                    {r.total_vancon_won_amount > 0 &&
                      ` · ${formatMoney(r.total_vancon_won_amount)}`}
                  </div>
                </div>
                <div className={cn("text-right font-mono tabular-nums", ts.text)}>
                  {r.submitted === 0 ? "—" : `${pct.toFixed(1)}%`}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function NearMissTable({
  rows,
}: {
  rows: Array<{
    id: string;
    job: string;
    bid_date: string;
    vancon: number | null;
    low: number | null;
    lost_by: number | null;
    percent_over: number | null;
    estimator: string | null;
  }>;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center gap-2">
        <Target className="h-4 w-4 text-warning" />
        <h4 className="text-sm font-semibold">Near misses</h4>
      </div>
      {rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">No close losses.</p>
      ) : (
        <div className="space-y-1.5">
          {rows.slice(0, 8).map((r) => (
            <div
              key={r.id}
              className="flex items-center justify-between gap-3 text-xs"
            >
              <div className="min-w-0 flex-1">
                <div className="truncate font-mono font-medium" title={r.job}>
                  {r.job}
                </div>
                <div className="text-[11px] text-muted-foreground">
                  {formatDate(r.bid_date)}
                  {r.estimator && ` · ${r.estimator}`}
                </div>
              </div>
              <div className="text-right font-mono tabular-nums text-warning">
                <div>
                  {r.lost_by != null ? `−${formatMoney(r.lost_by)}` : "—"}
                </div>
                <div className="text-[11px] opacity-80">
                  {r.percent_over != null
                    ? `+${(r.percent_over * 100).toFixed(2)}%`
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

function BigWinTable({
  rows,
}: {
  rows: Array<{
    id: string;
    job: string;
    bid_date: string;
    vancon: number;
    owner: string | null;
    bid_type: string | null;
    estimator: string | null;
  }>;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center gap-2">
        <Award className="h-4 w-4 text-primary" />
        <h4 className="text-sm font-semibold">Big wins</h4>
      </div>
      {rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">No wins recorded.</p>
      ) : (
        <div className="space-y-1.5">
          {rows.slice(0, 8).map((r) => (
            <div
              key={r.id}
              className="flex items-center justify-between gap-3 text-xs"
            >
              <div className="min-w-0 flex-1">
                <div className="truncate font-mono font-medium" title={r.job}>
                  {r.job}
                </div>
                <div className="truncate text-[11px] text-muted-foreground">
                  {formatDate(r.bid_date)}
                  {r.owner && ` · ${r.owner}`}
                  {r.bid_type && ` · ${r.bid_type}`}
                </div>
              </div>
              <div className="text-right font-mono tabular-nums text-primary">
                {formatMoney(r.vancon)}
              </div>
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
          AI-generated next actions for the bid book.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="rounded-lg border border-dashed border-border bg-muted/30 p-4 text-center">
          <p className="text-sm font-medium">Coming in Phase 6</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Claude will surface near-miss patterns to retarget, flag
            estimators with above-book win rates for new pursuits, and
            warn when an upcoming outlook bid sits in a crowded segment
            where VanCon historically loses — directly in this panel.
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

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

// Translate the schema's snake_case flag column into a readable label.
function humanizeFlag(flag: string): string {
  return flag
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
