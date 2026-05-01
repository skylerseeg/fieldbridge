import { useEffect, useMemo, useState } from "react";
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
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Camera,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  Database,
  ExternalLink,
  FileImage,
  FileText,
  FolderOpen,
  Gauge,
  Inbox,
  Image as ImageIcon,
  Info,
  Layers,
  Mail,
  MessageSquareQuote,
  Mic,
  Pin,
  Search,
  Sparkles,
  StickyNote,
  ThumbsDown,
  ThumbsUp,
  Trash2,
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
  clearResultLabel,
  fetchProjectSearchInsights,
  fetchProjectSearchList,
  fetchProjectSearchSummary,
  markResultNotRelevant,
  markResultUseful,
  pinResult,
  type DocType,
  type IndexStatus,
  type ListParams,
  type RelevanceLabel,
  type SearchListResponse,
  type SearchResultRow,
  type SortDir,
  type SortField,
} from "./project-search-api";

/**
 * Project Search module — Phase 5 page.
 *
 * Layout:
 *   ┌── 4 KPI tiles (corpus health) ───────────────────┐ ┌── Recommendations
 *   │  Documents · Projects · Freshness · Activity     │ │   (right rail)
 *   ├── Tabs: Overview · List · Insights ──────────────┤ │
 *   │  Overview: doc-type mix bar + project / aging /  │ │
 *   │            label feedback rollups                │ │
 *   │  List:     query box + paginated TanStack table  │ │
 *   │            with row-level useful/not-relevant/   │ │
 *   │            pin/clear mutations (optimistic)      │ │
 *   │  Insights: doc-type + label + aging mix, project │ │
 *   │            coverage table, doc-type impact bars, │ │
 *   │            top queries, top pinned, recent       │ │
 *   │            indexed items                         │ │
 *   └──────────────────────────────────────────────────┘ └──────────────────
 *
 * One row per indexed ChromaDB chunk. Two orthogonal classifications:
 *   - **DocType** (email / bid_pdf / proposal / drawing / rfi /
 *     change_order / work_order / photo / transcript / note / other)
 *     — drives icon and tone (light coloration so the *score* dominates).
 *   - **RelevanceLabel** (unlabeled / useful / not_relevant / pinned)
 *     — feedback signal flowing back into the embeddings layer.
 *
 * **Search-first.** Unlike the other Phase 5 marts, the List tab leads
 * with a prominent query box that drives the `q` param; an empty query
 * means filter-only browse (no `score`). All other filters
 * (project, doc type, label, date range) compose with the query and
 * the table updates server-side.
 *
 * Severity → token mapping (no new colors):
 *   primary  = good / dominant healthy bucket (fresh corpus, useful)
 *   info     = neutral fact (document count, unlabeled)
 *   warning  = caution (stale index, pinned, slow query)
 *   critical = alert (missing index, very stale corpus, not-relevant)
 *
 * Mutations flip only `relevance_label`, so optimistic updates are
 * safe — same `onMutate` cancel-snapshot-set pattern as the
 * recommendations and predictive-maintenance pages.
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

const docTypeStyles: Record<
  DocType,
  { tone: Tone; label: string; Icon: typeof FileText }
> = {
  email: { tone: "info", label: "Email", Icon: Mail },
  bid_pdf: { tone: "warn", label: "Bid PDF", Icon: FileText },
  proposal: { tone: "good", label: "Proposal", Icon: FileText },
  drawing: { tone: "info", label: "Drawing", Icon: FileImage },
  rfi: { tone: "warn", label: "RFI", Icon: MessageSquareQuote },
  change_order: { tone: "crit", label: "Change order", Icon: FileText },
  work_order: { tone: "warn", label: "Work order", Icon: FileText },
  photo: { tone: "info", label: "Photo", Icon: Camera },
  transcript: { tone: "info", label: "Transcript", Icon: Mic },
  note: { tone: "neutral", label: "Note", Icon: StickyNote },
  other: { tone: "neutral", label: "Other", Icon: ImageIcon },
};

const labelStyles: Record<
  RelevanceLabel,
  { tone: Tone; label: string; Icon: typeof ThumbsUp }
> = {
  unlabeled: { tone: "neutral", label: "Unlabeled", Icon: Inbox },
  useful: { tone: "good", label: "Useful", Icon: ThumbsUp },
  not_relevant: { tone: "crit", label: "Not relevant", Icon: ThumbsDown },
  pinned: { tone: "warn", label: "Pinned", Icon: Pin },
};

const indexStatusStyles: Record<
  IndexStatus,
  { tone: Tone; label: string }
> = {
  fresh: { tone: "good", label: "Fresh" },
  stale: { tone: "warn", label: "Stale" },
  missing: { tone: "crit", label: "Missing" },
};

// Display order for stacks.
const DOC_TYPE_ORDER: DocType[] = [
  "email",
  "bid_pdf",
  "proposal",
  "drawing",
  "rfi",
  "change_order",
  "work_order",
  "photo",
  "transcript",
  "note",
  "other",
];

const LABEL_ORDER: RelevanceLabel[] = [
  "unlabeled",
  "useful",
  "pinned",
  "not_relevant",
];

// Query key factory.
const keys = {
  all: ["project-search"] as const,
  summary: () => [...keys.all, "summary"] as const,
  list: (params: ListParams) => [...keys.all, "list", params] as const,
  insights: (topN: number) => [...keys.all, "insights", topN] as const,
};

// ──────────────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────────────

export function ProjectSearchPage() {
  return (
    <div className="p-6 lg:p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">
          Project Search
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Vector search across project memory — emails, drawings, RFIs,
          change orders, photos, and field notes indexed in ChromaDB.
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
    queryFn: fetchProjectSearchSummary,
  });

  // Four corpus-health tiles. Severity adapts:
  //   - Documents: info (neutral fact, just a count).
  //   - Projects covered: info / good if ≥10.
  //   - Freshness: 0–1d good · ≤7d info · ≤30d warn · else crit.
  //   - Search latency: <200ms good · <500ms info · <1500ms warn · else crit.
  const tiles = useMemo(() => {
    if (!data) return [];

    const projectsTone: Tone =
      data.distinct_projects === 0
        ? "neutral"
        : data.distinct_projects >= 10
          ? "good"
          : "info";

    const freshnessTone: Tone =
      data.index_age_days === null
        ? "neutral"
        : data.index_age_days <= 1
          ? "good"
          : data.index_age_days <= 7
            ? "info"
            : data.index_age_days <= 30
              ? "warn"
              : "crit";

    const latencyTone: Tone =
      data.avg_query_latency_ms === null
        ? "neutral"
        : data.avg_query_latency_ms < 200
          ? "good"
          : data.avg_query_latency_ms < 500
            ? "info"
            : data.avg_query_latency_ms < 1500
              ? "warn"
              : "crit";

    return [
      {
        key: "documents",
        tone: data.total_indexed_documents > 0 ? ("info" as Tone) : ("neutral" as Tone),
        Icon: Database,
        value: data.total_indexed_documents.toLocaleString(),
        label: "Documents indexed",
        sub: `${data.total_indexed_chunks.toLocaleString()} chunks · ${data.distinct_doc_types.toLocaleString()} types`,
      },
      {
        key: "projects",
        tone: projectsTone,
        Icon: FolderOpen,
        value: data.distinct_projects.toLocaleString(),
        label: "Projects covered",
        sub:
          data.pending_index_count > 0
            ? `${data.pending_index_count.toLocaleString()} pending`
            : data.stale_index_count > 0
              ? `${data.stale_index_count.toLocaleString()} stale`
              : "all current",
      },
      {
        key: "freshness",
        tone: freshnessTone,
        Icon: Clock,
        value:
          data.last_indexed_at === null
            ? "—"
            : data.index_age_days === null
              ? "—"
              : data.index_age_days === 0
                ? "today"
                : `${data.index_age_days.toLocaleString()}d`,
        label: "Index freshness",
        sub:
          data.last_indexed_at === null
            ? "no indexing yet"
            : `last on ${formatDate(data.last_indexed_at)}`,
      },
      {
        key: "activity",
        tone:
          data.recent_query_count_7d === 0
            ? ("neutral" as Tone)
            : ("info" as Tone),
        Icon: Activity,
        value: data.recent_query_count_7d.toLocaleString(),
        label: "Searches (7d)",
        sub:
          data.avg_query_latency_ms === null
            ? "no latency data"
            : `${formatLatency(data.avg_query_latency_ms)} avg · ${labelStyles.useful.label.toLowerCase()}=${data.useful_count.toLocaleString()}`,
        latencyTone,
      },
    ];
  }, [data]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Corpus snapshot</CardTitle>
          <CardDescription>
            ChromaDB index health · pulled from the project-search service
          </CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          {data && (
            <>
              <Badge variant="mono">
                {data.pinned_count.toLocaleString()} pinned
              </Badge>
              <Badge variant="mono">
                {data.useful_count.toLocaleString()} useful
              </Badge>
              <Badge variant="mono">
                {data.unlabeled_count.toLocaleString()} unlabeled
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
      <Tabs defaultValue="list" className="w-full">
        <CardHeader className="space-y-3">
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="list">Search</TabsTrigger>
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
    queryFn: fetchProjectSearchSummary,
  });
  const insights = useQuery({
    queryKey: keys.insights(10),
    queryFn: () => fetchProjectSearchInsights(10),
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

  // Headline: doc-type mix.
  const docTypeChart = DOC_TYPE_ORDER.map((k) => ({
    key: k,
    label: docTypeStyles[k].label,
    value: i.doc_type_breakdown[k],
    tone: docTypeStyles[k].tone,
  })).filter((d) => d.value > 0);

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
      <div className="md:col-span-2">
        <h3 className="text-sm font-semibold">Doc-type mix</h3>
        <p className="mb-3 text-xs text-muted-foreground">
          Distribution across {s.total_indexed_documents.toLocaleString()}{" "}
          indexed documents.
        </p>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={docTypeChart}
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
                interval={0}
                angle={-25}
                textAnchor="end"
                height={60}
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
                {docTypeChart.map((d) => (
                  <Cell key={d.key} fill={toneStyles[d.tone].fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-semibold">Coverage</h3>
        <SummaryRow
          label="Projects"
          value={s.distinct_projects.toLocaleString()}
        />
        <SummaryRow
          label="Doc types"
          value={s.distinct_doc_types.toLocaleString()}
        />
        <SummaryRow
          label="Chunks"
          value={s.total_indexed_chunks.toLocaleString()}
        />
        <div className="border-t border-border pt-3" />
        <h3 className="text-sm font-semibold">Index health</h3>
        <SummaryRow
          label="Last indexed"
          value={s.last_indexed_at ? formatDate(s.last_indexed_at) : "—"}
          sub={
            s.index_age_days !== null
              ? s.index_age_days === 0
                ? "today"
                : `${s.index_age_days}d ago`
              : undefined
          }
        />
        <SummaryRow
          label="Pending"
          value={s.pending_index_count.toLocaleString()}
        />
        <SummaryRow
          label="Stale"
          value={s.stale_index_count.toLocaleString()}
        />
        <div className="border-t border-border pt-3" />
        <h3 className="text-sm font-semibold">Aging (indexed)</h3>
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
        <div className="border-t border-border pt-3" />
        <h3 className="text-sm font-semibold">Feedback</h3>
        <SummaryRow
          label="Useful"
          value={s.useful_count.toLocaleString()}
        />
        <SummaryRow
          label="Pinned"
          value={s.pinned_count.toLocaleString()}
        />
        <SummaryRow
          label="Not relevant"
          value={s.not_relevant_count.toLocaleString()}
        />
        <SummaryRow
          label="Unlabeled"
          value={s.unlabeled_count.toLocaleString()}
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

// ── List (search) ─────────────────────────────────────────────────────

function ListTab() {
  // Search input is debounced into `query` so each keystroke doesn't
  // re-fire a vector search.
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const handle = window.setTimeout(() => {
      setQuery(searchInput.trim());
    }, 300);
    return () => window.clearTimeout(handle);
  }, [searchInput]);

  const [docType, setDocType] = useState<DocType | "all">("all");
  const [label, setLabel] = useState<RelevanceLabel | "all">("all");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [sorting, setSorting] = useState<SortingState>([
    { id: "relevance", desc: true },
  ]);

  // Reset page whenever any filter changes.
  useEffect(() => {
    setPage(1);
  }, [query, docType, label]);

  const sortBy = (sorting[0]?.id ?? "relevance") as SortField;
  const sortDir: SortDir = sorting[0]?.desc ? "desc" : "asc";

  const params: ListParams = useMemo(
    () => ({
      page,
      page_size: pageSize,
      sort_by: sortBy,
      sort_dir: sortDir,
      ...(query ? { q: query } : {}),
      ...(docType !== "all" ? { doc_type: docType } : {}),
      ...(label !== "all" ? { relevance_label: label } : {}),
    }),
    [page, pageSize, sortBy, sortDir, query, docType, label],
  );

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: keys.list(params),
    queryFn: () => fetchProjectSearchList(params),
    placeholderData: keepPreviousData,
  });

  const actions = useResultActions(params);

  const columns = useMemo<ColumnDef<SearchResultRow>[]>(
    () => [
      {
        accessorKey: "title",
        header: "Result",
        cell: ({ row }) => {
          const r = row.original;
          const dt = docTypeStyles[r.doc_type];
          const ts = toneStyles[dt.tone];
          return (
            <div className="flex flex-col gap-0.5">
              <span
                className="line-clamp-2 text-xs font-medium"
                title={r.title}
              >
                {r.title}
              </span>
              <span
                className="line-clamp-2 text-[11px] text-muted-foreground"
                title={r.snippet}
              >
                {r.snippet}
              </span>
              <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
                <span
                  className={cn(
                    "inline-flex w-fit items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                    ts.bg,
                    ts.text,
                  )}
                >
                  <dt.Icon className="h-3 w-3" />
                  {dt.label}
                </span>
                {r.project_label && (
                  <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
                    <FolderOpen className="h-3 w-3" />
                    <span className="line-clamp-1">{r.project_label}</span>
                  </span>
                )}
              </div>
            </div>
          );
        },
      },
      {
        id: "relevance",
        accessorKey: "score",
        header: "Score",
        cell: ({ row }) => {
          const r = row.original;
          if (r.score === null) {
            return <span className="text-xs text-muted-foreground">—</span>;
          }
          // Color the score by strength.
          const scoreTone: Tone =
            r.score >= 0.85
              ? "good"
              : r.score >= 0.7
                ? "info"
                : r.score >= 0.5
                  ? "warn"
                  : "neutral";
          const ts = toneStyles[scoreTone];
          const pct = Math.max(0, Math.min(100, r.score * 100));
          return (
            <div className="flex w-24 flex-col gap-0.5">
              <span
                className={cn("font-mono text-xs tabular-nums", ts.text)}
              >
                {r.score.toFixed(2)}
              </span>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full"
                  style={{ width: `${pct}%`, background: ts.fill }}
                />
              </div>
            </div>
          );
        },
      },
      {
        accessorKey: "indexed_at",
        header: "Indexed",
        cell: ({ row }) => {
          const r = row.original;
          // Color the index age by freshness.
          const ageTone: Tone =
            r.index_age_days <= 7
              ? "good"
              : r.index_age_days <= 30
                ? "info"
                : "warn";
          const ts = toneStyles[ageTone];
          return (
            <div className="flex flex-col gap-0.5">
              <span className={cn("font-mono text-xs tabular-nums", ts.text)}>
                {r.index_age_days === 0
                  ? "today"
                  : `${r.index_age_days.toFixed(0)}d`}
              </span>
              <span className="text-[10px] text-muted-foreground">
                {formatDate(r.indexed_at)}
              </span>
            </div>
          );
        },
      },
      {
        id: "label",
        accessorKey: "relevance_label",
        header: "Label",
        enableSorting: false,
        cell: ({ row }) => {
          const lb = labelStyles[row.original.relevance_label];
          const ts = toneStyles[lb.tone];
          return (
            <span
              className={cn(
                "inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
                ts.bg,
                ts.text,
              )}
            >
              <lb.Icon className="h-3 w-3" />
              {lb.label}
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
            actions.useful.isPending ||
            actions.notRelevant.isPending ||
            actions.pin.isPending ||
            actions.clear.isPending;
          return (
            <div className="flex items-center gap-1">
              <Button
                variant="outline"
                size="sm"
                disabled={isPending || r.relevance_label === "useful"}
                onClick={() => actions.useful.mutate({ id: r.id })}
                title="Mark useful"
              >
                <ThumbsUp className="h-3 w-3" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={isPending || r.relevance_label === "pinned"}
                onClick={() => actions.pin.mutate({ id: r.id })}
                title="Pin for later"
              >
                <Pin className="h-3 w-3" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={isPending || r.relevance_label === "not_relevant"}
                onClick={() => actions.notRelevant.mutate({ id: r.id })}
                title="Not relevant"
              >
                <ThumbsDown className="h-3 w-3" />
              </Button>
              {r.relevance_label !== "unlabeled" && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={isPending}
                  onClick={() => actions.clear.mutate({ id: r.id })}
                  title="Clear label"
                >
                  <Trash2 className="h-3 w-3" />
                </Button>
              )}
              {r.source_url && (
                <a
                  href={r.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex h-8 items-center justify-center rounded-md border border-input px-2 text-xs hover:bg-muted"
                  title="Open source"
                >
                  <ExternalLink className="h-3 w-3" />
                </a>
              )}
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
      {/* Search bar — wide query input drives the `q` param */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-96">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search emails, drawings, RFIs, photos…"
            className="pl-8"
          />
        </div>
        <Select<DocType | "all">
          value={docType}
          onChange={setDocType}
          options={[
            { value: "all", label: "All types" },
            { value: "email", label: "Email" },
            { value: "bid_pdf", label: "Bid PDF" },
            { value: "proposal", label: "Proposal" },
            { value: "drawing", label: "Drawing" },
            { value: "rfi", label: "RFI" },
            { value: "change_order", label: "Change order" },
            { value: "work_order", label: "Work order" },
            { value: "photo", label: "Photo" },
            { value: "transcript", label: "Transcript" },
            { value: "note", label: "Note" },
            { value: "other", label: "Other" },
          ]}
        />
        <Select<RelevanceLabel | "all">
          value={label}
          onChange={setLabel}
          options={[
            { value: "all", label: "All labels" },
            { value: "unlabeled", label: "Unlabeled" },
            { value: "useful", label: "Useful" },
            { value: "pinned", label: "Pinned" },
            { value: "not_relevant", label: "Not relevant" },
          ]}
        />
        {isFetching && (
          <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
            <Gauge className="h-3 w-3 animate-pulse" />
            searching…
          </span>
        )}
      </div>

      {/* Status strip — query state + perf */}
      {data && (
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          {data.effective_query ? (
            <span className="inline-flex items-center gap-1">
              <Search className="h-3 w-3" />
              <span className="font-mono">
                &quot;{data.effective_query}&quot;
              </span>
            </span>
          ) : (
            <span className="inline-flex items-center gap-1">
              <Layers className="h-3 w-3" />
              browse mode
            </span>
          )}
          <span>·</span>
          <span>{total.toLocaleString()} hits</span>
          <span>·</span>
          <span>{formatLatency(data.took_ms)}</span>
        </div>
      )}

      {isError && <ErrorBlock message="Couldn't load search results." />}
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
                  {query
                    ? "No matches for that query — try broader terms or remove a filter."
                    : "No indexed content matches the current filters."}
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
// Mutation hook — useful / not_relevant / pin / clear with optimistic
// updates. Each action only flips the row's `relevance_label`, so we
// can safely apply the predicted state into the list cache
// immediately, then roll back on error and re-sync on settled.
// ──────────────────────────────────────────────────────────────────────

interface ActionContext {
  previousList: SearchListResponse | undefined;
}

function useResultActions(params: ListParams) {
  const queryClient = useQueryClient();
  const listKey = keys.list(params);

  function applyLabel(id: string, nextLabel: RelevanceLabel): ActionContext {
    queryClient.cancelQueries({ queryKey: keys.all }).catch(() => {});
    const previousList =
      queryClient.getQueryData<SearchListResponse>(listKey);
    if (previousList) {
      queryClient.setQueryData<SearchListResponse>(listKey, {
        ...previousList,
        items: previousList.items.map((row) =>
          row.id === id ? { ...row, relevance_label: nextLabel } : row,
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

  const useful = useMutation<
    unknown,
    Error,
    { id: string; note?: string },
    ActionContext
  >({
    mutationFn: ({ id, note }) => markResultUseful(id, { note }),
    onMutate: ({ id }) => applyLabel(id, "useful"),
    onError: (_err, _vars, ctx) => rollback(ctx),
    onSettled: settle,
  });

  const notRelevant = useMutation<
    unknown,
    Error,
    { id: string; reason?: string },
    ActionContext
  >({
    mutationFn: ({ id, reason }) => markResultNotRelevant(id, { reason }),
    onMutate: ({ id }) => applyLabel(id, "not_relevant"),
    onError: (_err, _vars, ctx) => rollback(ctx),
    onSettled: settle,
  });

  const pin = useMutation<
    unknown,
    Error,
    { id: string; note?: string },
    ActionContext
  >({
    mutationFn: ({ id, note }) => pinResult(id, { note }),
    onMutate: ({ id }) => applyLabel(id, "pinned"),
    onError: (_err, _vars, ctx) => rollback(ctx),
    onSettled: settle,
  });

  const clear = useMutation<
    unknown,
    Error,
    { id: string; reason?: string },
    ActionContext
  >({
    mutationFn: ({ id, reason }) => clearResultLabel(id, { reason }),
    onMutate: ({ id }) => applyLabel(id, "unlabeled"),
    onError: (_err, _vars, ctx) => rollback(ctx),
    onSettled: settle,
  });

  const error =
    useful.error?.message ??
    notRelevant.error?.message ??
    pin.error?.message ??
    clear.error?.message ??
    null;

  return { useful, notRelevant, pin, clear, error };
}

// ── Insights ─────────────────────────────────────────────────────────

function InsightsTab() {
  const { data, isLoading, isError } = useQuery({
    queryKey: keys.insights(10),
    queryFn: () => fetchProjectSearchInsights(10),
  });

  if (isError) return <ErrorBlock message="Couldn't load insights." />;
  if (isLoading || !data) return <SkeletonBlock height="h-64" />;

  const docTypeChart = DOC_TYPE_ORDER.map((k) => ({
    key: k,
    label: docTypeStyles[k].label,
    value: data.doc_type_breakdown[k],
    tone: docTypeStyles[k].tone,
  })).filter((d) => d.value > 0);

  const labelChart = LABEL_ORDER.map((k) => ({
    key: k,
    label: labelStyles[k].label,
    value: data.relevance_breakdown[k],
    tone: labelStyles[k].tone,
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

  // For the doc-type-impact horizontal bar — scale to the largest signal_count.
  const docTypeImpactMax = data.doc_type_impact.reduce(
    (acc, r) => Math.max(acc, r.signal_count),
    0,
  );

  return (
    <div className="space-y-6">
      {/* Doc-type + Label breakdowns */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <BreakdownChart
          title="Doc type"
          subtitle="Indexed documents grouped by source class."
          data={docTypeChart}
          unitLabel="documents"
        />
        <BreakdownChart
          title="Feedback labels"
          subtitle="How users have labeled returned results."
          data={labelChart}
          unitLabel="labels"
        />
      </section>

      {/* Aging + Doc-type impact */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <BreakdownChart
          title="Aging (indexed)"
          subtitle="How long since each chunk was last embedded."
          data={agingChart}
          unitLabel="chunks"
        />
        <div>
          <h3 className="text-sm font-semibold">Signal by doc type</h3>
          <p className="mb-3 text-xs text-muted-foreground">
            Useful + pinned counts — which sources earn the most positive
            feedback.
          </p>
          {data.doc_type_impact.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No feedback data yet.
            </p>
          ) : (
            <div className="space-y-2">
              {data.doc_type_impact.map((m) => {
                const ds = docTypeStyles[m.doc_type];
                const ts = toneStyles[ds.tone];
                const pct =
                  docTypeImpactMax > 0
                    ? (m.signal_count / docTypeImpactMax) * 100
                    : 0;
                return (
                  <div key={m.doc_type} className="space-y-1">
                    <div className="flex items-center justify-between gap-3 text-xs">
                      <span className="inline-flex items-center gap-1.5 font-medium">
                        <ds.Icon className={cn("h-3.5 w-3.5", ts.text)} />
                        {ds.label}
                      </span>
                      <span className="font-mono tabular-nums">
                        {m.signal_count.toLocaleString()} signal
                        <span className="ml-1 text-muted-foreground">
                          {m.document_count.toLocaleString()} docs
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

      {/* Project coverage + Top queries */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="mb-3 flex items-center gap-2">
            <FolderOpen className="h-4 w-4 text-info" />
            <h4 className="text-sm font-semibold">Project coverage</h4>
          </div>
          {data.project_coverage.length === 0 ? (
            <p className="text-xs text-muted-foreground">No data.</p>
          ) : (
            <div className="space-y-1.5">
              {data.project_coverage.slice(0, 8).map((p) => {
                const st = indexStatusStyles[p.status];
                const ts = toneStyles[st.tone];
                return (
                  <div
                    key={p.project_id}
                    className="flex items-center justify-between gap-3 text-xs"
                  >
                    <div className="min-w-0 flex-1">
                      <div
                        className="truncate font-medium"
                        title={p.project_label}
                      >
                        {p.project_label}
                      </div>
                      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                        <span>{p.document_count.toLocaleString()} docs</span>
                        <span>·</span>
                        <span>{p.chunk_count.toLocaleString()} chunks</span>
                        <span>·</span>
                        <span>
                          {p.last_indexed_age_days === 0
                            ? "today"
                            : `${p.last_indexed_age_days}d ago`}
                        </span>
                      </div>
                    </div>
                    <span
                      className={cn(
                        "rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
                        ts.bg,
                        ts.text,
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

        <div className="rounded-lg border border-border bg-card p-4">
          <div className="mb-3 flex items-center gap-2">
            <Search className="h-4 w-4 text-info" />
            <h4 className="text-sm font-semibold">Top queries (7d)</h4>
          </div>
          {data.top_queries.length === 0 ? (
            <p className="text-xs text-muted-foreground">No queries yet.</p>
          ) : (
            <div className="space-y-1.5">
              {data.top_queries.slice(0, 8).map((q) => {
                const latencyTone: Tone =
                  q.avg_latency_ms < 200
                    ? "good"
                    : q.avg_latency_ms < 500
                      ? "info"
                      : q.avg_latency_ms < 1500
                        ? "warn"
                        : "crit";
                const ts = toneStyles[latencyTone];
                return (
                  <div
                    key={q.query}
                    className="flex items-center justify-between gap-3 text-xs"
                  >
                    <span
                      className="line-clamp-1 font-mono"
                      title={q.query}
                    >
                      {q.query}
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="font-mono tabular-nums">
                        {q.count.toLocaleString()}×
                      </span>
                      <span
                        className={cn(
                          "rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                          ts.bg,
                          ts.text,
                        )}
                      >
                        {formatLatency(q.avg_latency_ms)}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </section>

      {/* Top pinned + Recent indexed */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="mb-3 flex items-center gap-2">
            <Pin className="h-4 w-4 text-warning" />
            <h4 className="text-sm font-semibold">Top pinned</h4>
          </div>
          {data.top_pinned.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              Nothing pinned yet — bookmark useful results from the table.
            </p>
          ) : (
            <div className="space-y-1.5">
              {data.top_pinned.slice(0, 8).map((p) => {
                const dt = docTypeStyles[p.doc_type];
                return (
                  <div
                    key={p.id}
                    className="flex items-center justify-between gap-3 text-xs"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium" title={p.title}>
                        {p.title}
                      </div>
                      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                        <dt.Icon className="h-3 w-3" />
                        {dt.label}
                        {p.project_label && (
                          <>
                            <span>·</span>
                            <span className="line-clamp-1">
                              {p.project_label}
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                    <span className="font-mono text-[11px] text-muted-foreground">
                      {formatDate(p.pinned_at)}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <div className="mb-3 flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-primary" />
            <h4 className="text-sm font-semibold">Recently indexed</h4>
          </div>
          {data.recent_indexed.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No new content has been indexed yet.
            </p>
          ) : (
            <div className="space-y-1.5">
              {data.recent_indexed.slice(0, 8).map((r) => {
                const dt = docTypeStyles[r.doc_type];
                const ts = toneStyles[dt.tone];
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
                        <dt.Icon className="h-3 w-3" />
                        {dt.label}
                        {r.project_label && (
                          <>
                            <span>·</span>
                            <span className="line-clamp-1">
                              {r.project_label}
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                    <span
                      className={cn(
                        "rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                        ts.bg,
                        ts.text,
                      )}
                    >
                      {formatDate(r.indexed_at)}
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
              interval={0}
              angle={-25}
              textAnchor="end"
              height={60}
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
          <CardTitle>Synthesis</CardTitle>
        </div>
        <CardDescription>
          Run a query and Claude summarizes the matching corpus.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="rounded-lg border border-dashed border-border bg-muted/30 p-4 text-center">
          <p className="text-sm font-medium">Coming in Phase 6</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Type a question and Claude will read the top hits, cite the
            source documents, and draft a one-paragraph answer with
            inline links — directly in this panel.
          </p>
          <div className="mt-3 flex items-center justify-center gap-2">
            <Info className="h-4 w-4 text-muted-foreground/50" />
            <XCircle className="h-4 w-4 text-muted-foreground/50" />
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

// Compact latency: 120ms / 1.4s / 12s.
function formatLatency(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 10_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms / 1000)}s`;
}
