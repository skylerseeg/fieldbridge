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
  Boxes,
  ChevronLeft,
  ChevronRight,
  Clock,
  HardHat,
  Hash,
  HelpCircle,
  Layers,
  ListChecks,
  Package,
  Sparkles,
  TrendingUp,
  Truck,
  Users,
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
import { cn } from "@/lib/utils";

import {
  fetchCostCodingInsights,
  fetchCostCodingList,
  fetchCostCodingSummary,
  type CostCategory,
  type CostCodeListRow,
  type CostSizeTier,
  type ListParams,
  type SortDir,
  type SortField,
  type UsageTier,
} from "./cost-coding-api";

/**
 * Cost Coding module — Phase 5 page.
 *
 * Layout:
 *   ┌── 4 KPI tiles (catalog) ─────────────────────────┐ ┌── Recommendations
 *   │  Cost codes · Direct $ · Labor share · Uncosted  │ │   (right rail)
 *   ├── Tabs: Overview · List · Insights ──────────────┤ │
 *   │  Overview: bucket mix bar + catalog totals       │ │
 *   │  List:     paginated TanStack table              │ │
 *   │  Insights: category mix, size/usage breakdowns,  │ │
 *   │            top-by-cost / usage / hours, major-   │ │
 *   │            code rollup, uncosted codes           │ │
 *   └──────────────────────────────────────────────────┘ └──────────────────
 *
 * One entity per **HCSS activity code**. Three orthogonal axes:
 *   - cost category (which bucket dominates direct cost)
 *   - size tier (dollar magnitude)
 *   - usage tier (estimate count)
 *
 * Severity → token mapping (no new colors):
 *   primary  = good / dominant healthy bucket
 *   info     = neutral fact (counts, share)
 *   warning  = caution (light usage, mid coverage gap, equipment-heavy)
 *   critical = alert (uncosted hygiene gap, subcontract-heavy)
 *
 * Mutations: cost_coding endpoints are read-only. The query-key
 * factory is ready for Phase 6 (e.g. flagging codes for re-mapping).
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
  CostCategory,
  { tone: Tone; label: string; Icon: typeof HardHat }
> = {
  labor: { tone: "info", label: "Labor", Icon: HardHat },
  permanent_material: { tone: "good", label: "Perm. material", Icon: Package },
  construction_material: {
    tone: "good",
    label: "Constr. material",
    Icon: Boxes,
  },
  equipment: { tone: "warn", label: "Equipment", Icon: Truck },
  subcontract: { tone: "crit", label: "Subcontract", Icon: Users },
  mixed: { tone: "neutral", label: "Mixed", Icon: Layers },
  zero: { tone: "neutral", label: "Zero", Icon: HelpCircle },
};

const sizeStyles: Record<
  CostSizeTier,
  { tone: Tone; label: string }
> = {
  major: { tone: "good", label: "Major" },
  significant: { tone: "info", label: "Significant" },
  minor: { tone: "neutral", label: "Minor" },
  zero: { tone: "warn", label: "Zero" },
};

const usageStyles: Record<
  UsageTier,
  { tone: Tone; label: string }
> = {
  heavy: { tone: "good", label: "Heavy" },
  regular: { tone: "info", label: "Regular" },
  light: { tone: "neutral", label: "Light" },
  singleton: { tone: "neutral", label: "Singleton" },
};

// Display order for stacks.
const CATEGORY_ORDER: CostCategory[] = [
  "labor",
  "permanent_material",
  "construction_material",
  "equipment",
  "subcontract",
  "mixed",
  "zero",
];
const SIZE_ORDER: CostSizeTier[] = ["major", "significant", "minor", "zero"];
const USAGE_ORDER: UsageTier[] = ["heavy", "regular", "light", "singleton"];

// Query key factory.
const keys = {
  all: ["cost-coding"] as const,
  summary: () => [...keys.all, "summary"] as const,
  list: (params: ListParams) => [...keys.all, "list", params] as const,
  insights: (topN: number) => [...keys.all, "insights", topN] as const,
};

// ──────────────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────────────

export function CostCodingPage() {
  return (
    <div className="p-6 lg:p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Cost Coding</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          HCSS activity-code catalog with dominant cost bucket, dollar
          magnitude, and usage breadth across the estimate book.
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
    queryFn: fetchCostCodingSummary,
  });

  // Four catalog-oriented tiles. Severity adapts:
  //   - Cost codes: info.
  //   - Direct $: info (raw scope).
  //   - Labor share: info — neutral classification, not severity.
  //   - Uncosted: 0 = good · share <5% = warn · else crit.
  const tiles = useMemo(() => {
    if (!data) return [];

    const laborShare =
      data.total_direct_cost > 0
        ? data.total_labor_cost / data.total_direct_cost
        : 0;

    const uncostedShare =
      data.total_codes > 0 ? data.uncosted_codes / data.total_codes : 0;
    const uncostedTone: Tone =
      data.uncosted_codes === 0
        ? "good"
        : uncostedShare < 0.05
          ? "warn"
          : "crit";

    return [
      {
        key: "codes",
        tone: "info" as Tone,
        Icon: Hash,
        value: data.total_codes.toLocaleString(),
        label: "Cost codes",
        sub: `${data.distinct_estimates.toLocaleString()} estimates · ${data.total_activities.toLocaleString()} rows`,
      },
      {
        key: "direct",
        tone: "info" as Tone,
        Icon: TrendingUp,
        value: formatMoney(data.total_direct_cost),
        label: "Direct cost",
        sub: `${formatHours(data.total_man_hours)} man-hours`,
      },
      {
        key: "labor",
        tone: "info" as Tone,
        Icon: HardHat,
        value:
          data.total_direct_cost > 0
            ? `${(laborShare * 100).toFixed(1)}%`
            : "—",
        label: "Labor share",
        sub:
          data.total_direct_cost > 0
            ? formatMoney(data.total_labor_cost)
            : "no direct cost",
      },
      {
        key: "uncosted",
        tone: uncostedTone,
        Icon: AlertTriangle,
        value: data.uncosted_codes.toLocaleString(),
        label: "Uncosted codes",
        sub:
          data.total_codes > 0
            ? `${(uncostedShare * 100).toFixed(1)}% of catalog`
            : "no codes",
      },
    ];
  }, [data]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Catalog snapshot</CardTitle>
          <CardDescription>
            Activity-code rollup · pulled from the cost-coding marts
          </CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          {data && (
            <>
              <Badge variant="mono">
                {data.codes_with_labor.toLocaleString()} w/ labor
              </Badge>
              <Badge variant="mono">
                {data.codes_with_equipment.toLocaleString()} w/ equip
              </Badge>
              <Badge variant="mono">
                {data.codes_with_subcontract.toLocaleString()} w/ subs
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
    queryFn: fetchCostCodingSummary,
  });

  if (summary.isError) {
    return <ErrorBlock message="Couldn't load overview." />;
  }
  if (summary.isLoading || !summary.data) {
    return <SkeletonBlock height="h-64" />;
  }

  const s = summary.data;

  // Headline: dollar mix across the five cost buckets — authoritative
  // totals straight from the summary endpoint.
  const bucketChart: {
    key: CostCategory;
    label: string;
    value: number;
    tone: Tone;
  }[] = [
    {
      key: "labor",
      label: "Labor",
      value: s.total_labor_cost,
      tone: categoryStyles.labor.tone,
    },
    {
      key: "permanent_material",
      label: "Perm. mat.",
      value: s.total_permanent_material_cost,
      tone: categoryStyles.permanent_material.tone,
    },
    {
      key: "construction_material",
      label: "Constr. mat.",
      value: s.total_construction_material_cost,
      tone: categoryStyles.construction_material.tone,
    },
    {
      key: "equipment",
      label: "Equipment",
      value: s.total_equipment_cost,
      tone: categoryStyles.equipment.tone,
    },
    {
      key: "subcontract",
      label: "Subcontract",
      value: s.total_subcontract_cost,
      tone: categoryStyles.subcontract.tone,
    },
  ];

  const total = s.total_direct_cost;

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
      <div className="md:col-span-2">
        <h3 className="text-sm font-semibold">Direct cost mix</h3>
        <p className="mb-3 text-xs text-muted-foreground">
          Total dollars by bucket across {s.total_codes.toLocaleString()}{" "}
          codes.
        </p>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={bucketChart}
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
                tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                stroke="hsl(var(--border))"
                tickFormatter={(v: number) => formatMoney(v)}
              />
              <RechartsTooltip
                cursor={{ fill: "hsl(var(--muted))" }}
                contentStyle={{
                  background: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                formatter={(v: number) => formatMoney(v)}
              />
              <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                {bucketChart.map((d) => (
                  <Cell key={d.key} fill={toneStyles[d.tone].fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-semibold">Catalog</h3>
        <SummaryRow
          label="Cost codes"
          value={s.total_codes.toLocaleString()}
        />
        <SummaryRow
          label="Estimates"
          value={s.distinct_estimates.toLocaleString()}
        />
        <SummaryRow
          label="Activity rows"
          value={s.total_activities.toLocaleString()}
        />
        <div className="border-t border-border pt-3" />
        <h3 className="text-sm font-semibold">Money</h3>
        <SummaryRow label="Direct cost" value={formatMoney(total)} />
        <SummaryRow
          label="Man-hours"
          value={formatHours(s.total_man_hours)}
        />
        <div className="border-t border-border pt-3" />
        <h3 className="text-sm font-semibold">Coverage</h3>
        <SummaryRow
          label="Codes w/ labor"
          value={s.codes_with_labor.toLocaleString()}
          sub={shareSub(s.codes_with_labor, s.total_codes)}
        />
        <SummaryRow
          label="Codes w/ equipment"
          value={s.codes_with_equipment.toLocaleString()}
          sub={shareSub(s.codes_with_equipment, s.total_codes)}
        />
        <SummaryRow
          label="Codes w/ subs"
          value={s.codes_with_subcontract.toLocaleString()}
          sub={shareSub(s.codes_with_subcontract, s.total_codes)}
        />
        {s.uncosted_codes > 0 && (
          <SummaryRow
            label="Uncosted"
            value={s.uncosted_codes.toLocaleString()}
            sub={shareSub(s.uncosted_codes, s.total_codes)}
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

function shareSub(part: number, total: number): string | undefined {
  if (total <= 0 || part <= 0) return undefined;
  return `${((part / total) * 100).toFixed(0)}% of catalog`;
}

// ── List ─────────────────────────────────────────────────────────────

function ListTab() {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<CostCategory | "all">("all");
  const [sizeTier, setSizeTier] = useState<CostSizeTier | "all">("all");
  const [usageTier, setUsageTier] = useState<UsageTier | "all">("all");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [sorting, setSorting] = useState<SortingState>([
    { id: "total_direct_cost", desc: true },
  ]);

  const sortBy = (sorting[0]?.id ?? "total_direct_cost") as SortField;
  const sortDir: SortDir = sorting[0]?.desc ? "desc" : "asc";

  const params: ListParams = useMemo(
    () => ({
      page,
      page_size: pageSize,
      sort_by: sortBy,
      sort_dir: sortDir,
      ...(search.trim() ? { search: search.trim() } : {}),
      ...(category !== "all" ? { cost_category: category } : {}),
      ...(sizeTier !== "all" ? { size_tier: sizeTier } : {}),
      ...(usageTier !== "all" ? { usage_tier: usageTier } : {}),
    }),
    [page, pageSize, sortBy, sortDir, search, category, sizeTier, usageTier],
  );

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: keys.list(params),
    queryFn: () => fetchCostCodingList(params),
    placeholderData: keepPreviousData,
  });

  const columns = useMemo<ColumnDef<CostCodeListRow>[]>(
    () => [
      {
        accessorKey: "code",
        header: "Code",
        cell: ({ row }) => (
          <div className="flex flex-col gap-0.5">
            <span className="font-mono font-medium">{row.original.code}</span>
            {row.original.description && (
              <span
                className="line-clamp-2 text-[11px] text-muted-foreground"
                title={row.original.description}
              >
                {row.original.description}
              </span>
            )}
            {row.original.major_code && (
              <span className="font-mono text-[10px] text-muted-foreground">
                major {row.original.major_code}
              </span>
            )}
          </div>
        ),
      },
      {
        accessorKey: "estimate_count",
        header: "Estimates",
        cell: ({ row }) => {
          const u = usageStyles[row.original.usage_tier];
          const ts = toneStyles[u.tone];
          return (
            <div className="flex flex-col gap-0.5">
              <span className="font-mono tabular-nums">
                {row.original.estimate_count.toLocaleString()}
              </span>
              <span
                className={cn(
                  "inline-flex w-fit items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                  ts.bg,
                  ts.text,
                )}
              >
                {u.label.toLowerCase()}
              </span>
            </div>
          );
        },
      },
      {
        accessorKey: "total_direct_cost",
        header: "Direct cost",
        cell: ({ row }) => {
          const sz = sizeStyles[row.original.size_tier];
          const ts = toneStyles[sz.tone];
          if (row.original.total_direct_cost === 0) {
            return (
              <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
                <AlertTriangle className="h-3 w-3" />
                uncosted
              </span>
            );
          }
          return (
            <div className="flex flex-col gap-0.5">
              <span className="font-mono tabular-nums">
                {formatMoney(row.original.total_direct_cost)}
              </span>
              <span
                className={cn(
                  "inline-flex w-fit items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                  ts.bg,
                  ts.text,
                )}
              >
                {sz.label.toLowerCase()}
              </span>
            </div>
          );
        },
      },
      {
        accessorKey: "total_man_hours",
        header: "Hours",
        cell: ({ row }) => (
          <span className="font-mono text-xs tabular-nums">
            {row.original.total_man_hours > 0
              ? formatHours(row.original.total_man_hours)
              : "—"}
          </span>
        ),
      },
      {
        id: "cost_category",
        accessorKey: "cost_category",
        header: "Category",
        enableSorting: false,
        cell: ({ row }) => {
          const c = categoryStyles[row.original.cost_category];
          const ts = toneStyles[c.tone];
          return (
            <span
              className={cn(
                "inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
                ts.bg,
                ts.text,
              )}
            >
              <c.Icon className="h-3 w-3" />
              {c.label}
            </span>
          );
        },
      },
      {
        id: "bucket_share",
        header: "Top bucket",
        enableSorting: false,
        cell: ({ row }) => {
          const r = row.original;
          if (r.total_direct_cost <= 0) {
            return <span className="text-xs text-muted-foreground">—</span>;
          }
          const buckets: { key: CostCategory; value: number }[] = [
            { key: "labor", value: r.labor_cost },
            { key: "permanent_material", value: r.permanent_material_cost },
            {
              key: "construction_material",
              value: r.construction_material_cost,
            },
            { key: "equipment", value: r.equipment_cost },
            { key: "subcontract", value: r.subcontract_cost },
          ];
          const top = buckets.reduce(
            (acc, b) => (b.value > acc.value ? b : acc),
            buckets[0],
          );
          if (top.value <= 0) {
            return <span className="text-xs text-muted-foreground">—</span>;
          }
          const pct = (top.value / r.total_direct_cost) * 100;
          const c = categoryStyles[top.key];
          return (
            <div className="flex flex-col gap-0.5">
              <span className="text-xs font-medium">{c.label}</span>
              <div className="flex items-center gap-2">
                <div className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full"
                    style={{
                      width: `${Math.min(100, pct)}%`,
                      background: toneStyles[c.tone].fill,
                    }}
                  />
                </div>
                <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                  {pct.toFixed(0)}%
                </span>
              </div>
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
          placeholder="Search code or description…"
          className="w-full sm:w-72"
        />
        <Select<CostCategory | "all">
          value={category}
          onChange={(v) => {
            setCategory(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All categories" },
            { value: "labor", label: "Labor" },
            { value: "permanent_material", label: "Perm. material" },
            { value: "construction_material", label: "Constr. material" },
            { value: "equipment", label: "Equipment" },
            { value: "subcontract", label: "Subcontract" },
            { value: "mixed", label: "Mixed" },
            { value: "zero", label: "Zero" },
          ]}
        />
        <Select<CostSizeTier | "all">
          value={sizeTier}
          onChange={(v) => {
            setSizeTier(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All sizes" },
            { value: "major", label: "Major" },
            { value: "significant", label: "Significant" },
            { value: "minor", label: "Minor" },
            { value: "zero", label: "Zero" },
          ]}
        />
        <Select<UsageTier | "all">
          value={usageTier}
          onChange={(v) => {
            setUsageTier(v);
            setPage(1);
          }}
          options={[
            { value: "all", label: "All usage" },
            { value: "heavy", label: "Heavy" },
            { value: "regular", label: "Regular" },
            { value: "light", label: "Light" },
            { value: "singleton", label: "Singleton" },
          ]}
        />
        {isFetching && (
          <span className="text-[11px] text-muted-foreground">refreshing…</span>
        )}
      </div>

      {isError && <ErrorBlock message="Couldn't load cost-code list." />}

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
                  No cost codes match the current filters.
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
    queryFn: () => fetchCostCodingInsights(10),
  });

  if (isError) return <ErrorBlock message="Couldn't load insights." />;
  if (isLoading || !data) return <SkeletonBlock height="h-64" />;

  const categoryCountChart = CATEGORY_ORDER.map((k) => ({
    key: k,
    label: categoryStyles[k].label,
    value: data.category_breakdown[k],
    tone: categoryStyles[k].tone,
  }));

  const sizeChart = SIZE_ORDER.map((k) => ({
    key: k,
    label: sizeStyles[k].label,
    value: data.size_tier_breakdown[k],
    tone: sizeStyles[k].tone,
  }));

  const usageChart = USAGE_ORDER.map((k) => ({
    key: k,
    label: usageStyles[k].label,
    value: data.usage_tier_breakdown[k],
    tone: usageStyles[k].tone,
  }));

  return (
    <div className="space-y-6">
      {/* Category share + count */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <h3 className="text-sm font-semibold">Spend share by category</h3>
          <p className="mb-3 text-xs text-muted-foreground">
            Each category's slice of total direct cost.
          </p>
          {data.category_mix.length === 0 ? (
            <p className="text-xs text-muted-foreground">No data.</p>
          ) : (
            <div className="space-y-2">
              {data.category_mix.map((m) => {
                const c = categoryStyles[m.category];
                const ts = toneStyles[c.tone];
                const pct = m.share_of_total * 100;
                return (
                  <div key={m.category} className="space-y-1">
                    <div className="flex items-center justify-between gap-3 text-xs">
                      <span className="inline-flex items-center gap-1.5 font-medium">
                        <c.Icon className={cn("h-3.5 w-3.5", ts.text)} />
                        {c.label}
                      </span>
                      <span className="font-mono tabular-nums">
                        {formatMoney(m.total_direct_cost)}{" "}
                        <span className="ml-1 text-muted-foreground">
                          {pct.toFixed(1)}% · {m.code_count} codes
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

        <div>
          <h3 className="text-sm font-semibold">Code count by category</h3>
          <p className="mb-3 text-xs text-muted-foreground">
            How many codes fall in each dominance bucket.
          </p>
          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={categoryCountChart}
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
                  dataKey="label"
                  width={120}
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
                  {categoryCountChart.map((d) => (
                    <Cell key={d.key} fill={toneStyles[d.tone].fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </section>

      {/* Size + usage tier mix */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <BreakdownChart
          title="Size tier"
          subtitle="Distribution of codes across dollar magnitude tiers."
          data={sizeChart}
        />
        <BreakdownChart
          title="Usage tier"
          subtitle="How broadly the codes are used across estimates."
          data={usageChart}
        />
      </section>

      {/* Top-by-X tables */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <TopCodeTable
          title="Top by direct cost"
          icon={<TrendingUp className="h-4 w-4 text-info" />}
          rows={data.top_by_cost}
          metricLabel="cost"
        />
        <TopCodeTable
          title="Top by usage"
          icon={<ListChecks className="h-4 w-4 text-info" />}
          rows={data.top_by_usage}
          metricLabel="usage"
        />
        <TopCodeTable
          title="Top by hours"
          icon={<Clock className="h-4 w-4 text-info" />}
          rows={data.top_by_hours}
          metricLabel="hours"
        />
      </section>

      {/* Major code rollup + Uncosted hygiene */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="mb-3 flex items-center gap-2">
            <Layers className="h-4 w-4 text-info" />
            <h4 className="text-sm font-semibold">Major-code rollup</h4>
          </div>
          {data.top_major_codes.length === 0 ? (
            <p className="text-xs text-muted-foreground">No data.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                    <th className="py-2 font-medium">Major</th>
                    <th className="py-2 text-right font-medium">Codes</th>
                    <th className="py-2 text-right font-medium">Estimates</th>
                    <th className="py-2 text-right font-medium">Direct $</th>
                  </tr>
                </thead>
                <tbody>
                  {data.top_major_codes.map((m) => (
                    <tr key={m.major_code} className="border-b border-border/50">
                      <td className="py-2">
                        <div className="font-mono font-medium">
                          {m.major_code}
                        </div>
                        {m.example_description && (
                          <div className="line-clamp-1 text-[11px] text-muted-foreground">
                            {m.example_description}
                          </div>
                        )}
                      </td>
                      <td className="py-2 text-right font-mono tabular-nums">
                        {m.code_count.toLocaleString()}
                      </td>
                      <td className="py-2 text-right font-mono tabular-nums">
                        {m.estimate_count.toLocaleString()}
                      </td>
                      <td className="py-2 text-right font-mono tabular-nums">
                        {formatMoney(m.total_direct_cost)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <div className="mb-3 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-warning" />
            <h4 className="text-sm font-semibold">Uncosted hygiene</h4>
          </div>
          <p className="mb-3 text-xs text-muted-foreground">
            Codes with zero direct cost across every estimate they
            appear in — review for re-mapping or retirement.
          </p>
          {data.uncosted_codes.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No uncosted codes — clean catalog.
            </p>
          ) : (
            <div className="space-y-1.5">
              {data.uncosted_codes.slice(0, 8).map((u) => (
                <div
                  key={u.code}
                  className="flex items-center justify-between gap-3 text-xs"
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-mono font-medium">
                      {u.code}
                    </div>
                    {u.description && (
                      <div className="truncate text-[11px] text-muted-foreground">
                        {u.description}
                      </div>
                    )}
                  </div>
                  <div className="text-right text-[11px] text-muted-foreground">
                    {u.estimate_count} estimates
                  </div>
                </div>
              ))}
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
        {subtitle} {total.toLocaleString()} codes classified.
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

function TopCodeTable({
  title,
  icon,
  rows,
  metricLabel,
}: {
  title: string;
  icon: React.ReactNode;
  rows: Array<{
    code: string;
    description: string | null;
    estimate_count: number;
    total_direct_cost: number;
    total_man_hours: number;
    cost_category: CostCategory;
  }>;
  metricLabel: "cost" | "usage" | "hours";
}) {
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
          {rows.slice(0, 8).map((r) => {
            const c = categoryStyles[r.cost_category];
            const ts = toneStyles[c.tone];
            const metric =
              metricLabel === "cost"
                ? formatMoney(r.total_direct_cost)
                : metricLabel === "usage"
                  ? `${r.estimate_count} est.`
                  : formatHours(r.total_man_hours);
            return (
              <div
                key={r.code}
                className="flex items-center justify-between gap-3 text-xs"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate font-mono font-medium" title={r.code}>
                    {r.code}
                  </div>
                  {r.description && (
                    <div
                      className="truncate text-[11px] text-muted-foreground"
                      title={r.description}
                    >
                      {r.description}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "hidden rounded-full px-1.5 py-0.5 text-[10px] font-medium sm:inline-flex",
                      ts.bg,
                      ts.text,
                    )}
                  >
                    {c.label}
                  </span>
                  <span className="font-mono text-xs tabular-nums">
                    {metric}
                  </span>
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
          AI-generated next actions for the cost-code catalog.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="rounded-lg border border-dashed border-border bg-muted/30 p-4 text-center">
          <p className="text-sm font-medium">Coming in Phase 6</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Claude will flag uncosted codes for retirement, surface
            major-code rollups drifting from the standard chart, and
            recommend re-mappings when a code's description varies
            wildly across estimates — directly in this panel.
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
