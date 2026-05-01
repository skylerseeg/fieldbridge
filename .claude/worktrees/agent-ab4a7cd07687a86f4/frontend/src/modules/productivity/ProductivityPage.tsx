import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
import {
  AlertTriangle,
  Check,
  Clock,
  Construction,
  Gauge,
  HardHat,
  HelpCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

import { AttentionTab } from "./AttentionTab";
import { JobDetailSheet } from "./JobDetailSheet";
import {
  fetchProductivitySummary,
  type PhaseStatus,
} from "./productivity-api";

const keys = {
  all: ["productivity"] as const,
  summary: () => [...keys.all, "summary"] as const,
};

type StatusKey = Exclude<PhaseStatus, "unknown"> | "unknown";

const phaseTileConfig: Record<
  StatusKey,
  {
    key: keyof Pick<
      import("./productivity-api").ProductivitySummary,
      | "phases_complete"
      | "phases_on_track"
      | "phases_behind_pace"
      | "phases_over_budget"
      | "phases_unknown"
    >;
    border: string;
    bg: string;
    text: string;
    fill: string;
    label: string;
    Icon: typeof Check;
  }
> = {
  complete: {
    key: "phases_complete",
    border: "border-l-primary",
    bg: "bg-primary/10",
    text: "text-primary",
    fill: "hsl(var(--primary))",
    label: "Complete",
    Icon: Check,
  },
  on_track: {
    key: "phases_on_track",
    border: "border-l-info",
    bg: "bg-info/10",
    text: "text-info",
    fill: "hsl(var(--info))",
    label: "On track",
    Icon: Gauge,
  },
  behind_pace: {
    key: "phases_behind_pace",
    border: "border-l-warning",
    bg: "bg-warning/10",
    text: "text-warning",
    fill: "hsl(var(--warning))",
    label: "Behind pace",
    Icon: AlertTriangle,
  },
  over_budget: {
    key: "phases_over_budget",
    border: "border-l-critical",
    bg: "bg-critical/10",
    text: "text-critical",
    fill: "hsl(var(--critical))",
    label: "Over budget",
    Icon: Construction,
  },
  unknown: {
    key: "phases_unknown",
    border: "border-l-accent",
    bg: "bg-muted",
    text: "text-muted-foreground",
    fill: "hsl(var(--accent))",
    label: "Unknown",
    Icon: HelpCircle,
  },
};

const chartOrder: StatusKey[] = [
  "complete",
  "on_track",
  "behind_pace",
  "over_budget",
  "unknown",
];

export function ProductivityPage() {
  const [sheetOpen, setSheetOpen] = useState(false);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  const openJob = (jobId: string) => {
    setSelectedJobId(jobId);
    setSheetOpen(true);
  };

  return (
    <div className="p-6 lg:p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Productivity</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Job and phase hours from labor and equipment productivity marts —
          KPIs, attention queue, and per-job drill-down.
        </p>
      </header>

      <div className="space-y-6">
        <KpiStrip />
        <ContentTabs onJobSelect={openJob} />
      </div>

      <JobDetailSheet
        jobId={selectedJobId}
        open={sheetOpen}
        onOpenChange={(next) => {
          setSheetOpen(next);
          if (!next) setSelectedJobId(null);
        }}
      />
    </div>
  );
}

function KpiStrip() {
  const { data, isLoading, isError } = useQuery({
    queryKey: keys.summary(),
    queryFn: () => fetchProductivitySummary(),
  });

  const tiles = useMemo(() => {
    if (!data) return [];
    return chartOrder.map((status) => {
      const cfg = phaseTileConfig[status];
      return { status, count: data[cfg.key], ...cfg };
    });
  }, [data]);

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Hours & phase health</CardTitle>
          <CardDescription>
            Combined labor and equipment hours with worst-case phase status
            across both marts.
          </CardDescription>
        </div>
        {data && (
          <div className="flex flex-wrap gap-2">
            <Badge variant="mono">{data.total_jobs.toLocaleString()} jobs</Badge>
            <Badge variant="mono">
              {data.total_phases.toLocaleString()} phases
            </Badge>
            <Badge variant="mono">
              {data.combined_actual_hours.toLocaleString(undefined, {
                maximumFractionDigits: 0,
              })}{" "}
              act. hrs
            </Badge>
            {data.combined_percent_used != null && (
              <Badge variant="mono">
                {formatPct(data.combined_percent_used)} of est. hours used
              </Badge>
            )}
          </div>
        )}
      </CardHeader>
      <CardContent>
        {isError && (
          <div className="rounded-md border border-critical/30 bg-critical/5 p-3 text-sm text-critical">
            Could not load productivity summary.
          </div>
        )}
        {isLoading && <SkeletonGrid />}
        {data && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {tiles.map((t) => (
              <div
                key={t.status}
                className={cn(
                  "flex flex-col gap-1.5 rounded-lg border border-border border-l-4 bg-card px-4 py-3.5",
                  t.border,
                )}
              >
                <div
                  className={cn(
                    "flex h-7 w-7 items-center justify-center rounded-md",
                    t.bg,
                  )}
                >
                  <t.Icon className={cn("h-3.5 w-3.5", t.text)} />
                </div>
                <div className="font-mono text-2xl font-semibold">{t.count}</div>
                <div className="text-xs font-medium">{t.label}</div>
                <div className="text-[11px] text-muted-foreground">phases</div>
              </div>
            ))}
          </div>
        )}
        {data && (
          <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
            <ResourceMini
              label="Labor"
              totals={data.labor_totals}
              icon={HardHat}
            />
            <ResourceMini
              label="Equipment"
              totals={data.equipment_totals}
              icon={Construction}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ResourceMini({
  label,
  totals,
  icon: Icon,
}: {
  label: string;
  totals: import("./productivity-api").ResourceTotals;
  icon: typeof HardHat;
}) {
  return (
    <div className="rounded-lg border border-border bg-muted/20 p-4">
      <div className="mb-2 flex items-center gap-2">
        <Icon className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm font-semibold">{label}</span>
        <Badge variant="outline" className="ml-auto text-[10px]">
          {totals.phases} phases
        </Badge>
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <div className="text-muted-foreground">Actual hrs</div>
          <div className="font-mono font-semibold tabular-nums">
            {totals.actual_hours.toLocaleString(undefined, {
              maximumFractionDigits: 0,
            })}
          </div>
        </div>
        <div>
          <div className="text-muted-foreground">Est. hrs</div>
          <div className="font-mono font-semibold tabular-nums">
            {totals.est_hours.toLocaleString(undefined, {
              maximumFractionDigits: 0,
            })}
          </div>
        </div>
        <div>
          <div className="text-muted-foreground">Avg % complete</div>
          <div className="font-mono font-semibold tabular-nums">
            {formatPct(totals.avg_percent_complete)}
          </div>
        </div>
        <div>
          <div className="text-muted-foreground">% used</div>
          <div className="font-mono font-semibold tabular-nums">
            {totals.percent_used == null ? "—" : formatPct(totals.percent_used)}
          </div>
        </div>
      </div>
    </div>
  );
}

function ContentTabs({
  onJobSelect,
}: {
  onJobSelect: (jobId: string) => void;
}) {
  return (
    <Card>
      <Tabs defaultValue="overview" className="w-full">
        <CardHeader className="space-y-3">
          <TabsList className="flex h-auto flex-wrap justify-start">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="attention">Attention</TabsTrigger>
          </TabsList>
        </CardHeader>
        <CardContent>
          <TabsContent value="overview" className="mt-0">
            <OverviewTab />
          </TabsContent>
          <TabsContent value="attention" className="mt-0">
            <AttentionTab onJobSelect={onJobSelect} />
          </TabsContent>
        </CardContent>
      </Tabs>
    </Card>
  );
}

function OverviewTab() {
  const { data, isLoading, isError } = useQuery({
    queryKey: keys.summary(),
    queryFn: () => fetchProductivitySummary(),
  });

  if (isError) {
    return (
      <div className="rounded-md border border-critical/30 bg-critical/5 p-3 text-sm text-critical">
        Could not load overview.
      </div>
    );
  }
  if (isLoading || !data) {
    return <SkeletonBlock className="h-64" />;
  }

  const chartData = chartOrder.map((status) => ({
    status,
    count: data[phaseTileConfig[status].key],
    label: phaseTileConfig[status].label,
  }));

  const combinedEst = data.combined_est_hours;
  const laborShare =
    combinedEst > 0 ? data.labor_totals.est_hours / combinedEst : 0;
  const equipShare =
    combinedEst > 0 ? data.equipment_totals.est_hours / combinedEst : 0;

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <div className="lg:col-span-2">
        <h3 className="text-sm font-semibold">Phases by status</h3>
        <p className="mb-3 text-xs text-muted-foreground">
          Worst-case status per phase across labor and equipment.
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
              />
              <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                {chartData.map((d) => (
                  <Cell key={d.status} fill={phaseTileConfig[d.status].fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div className="space-y-3">
        <h3 className="text-sm font-semibold">Estimated hour mix</h3>
        <p className="text-xs text-muted-foreground">
          Share of total estimated hours (labor vs equipment marts).
        </p>
        <SummaryRow label="Labor est." value={formatPct(laborShare)} />
        <SummaryRow label="Equipment est." value={formatPct(equipShare)} />
        <div className="border-t border-border pt-3" />
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Clock className="h-3.5 w-3.5" />
          Combined actual{" "}
          <span className="font-mono font-semibold text-foreground">
            {data.combined_actual_hours.toLocaleString(undefined, {
              maximumFractionDigits: 0,
            })}
          </span>{" "}
          hrs
        </div>
      </div>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="font-mono text-base font-semibold tabular-nums">
        {value}
      </span>
    </div>
  );
}

function formatPct(n: number): string {
  return `${(n * 100).toFixed(0)}%`;
}

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
      {Array.from({ length: 5 }).map((_, i) => (
        <SkeletonBlock key={i} className="h-24" />
      ))}
    </div>
  );
}

function SkeletonBlock({ className }: { className?: string }) {
  return (
    <div className={cn("animate-pulse rounded-md bg-muted", className)} />
  );
}
