import { useQuery } from "@tanstack/react-query";
import {
  AlertOctagon,
  AlertTriangle,
  Banknote,
  Briefcase,
  Calendar,
  Construction,
  DollarSign,
  Gauge,
  Hourglass,
  Info,
  TrendingDown,
  TrendingUp,
  Users,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

import {
  fetchExecutiveAttention,
  fetchExecutiveSummary,
  fetchExecutiveTrend,
  type AttentionItem,
  type AttentionKind,
  type ExecutiveSummary,
} from "./executive-dashboard-api";

/**
 * Executive Dashboard — cross-module KPI rollup.
 *
 * Layout:
 *   ┌── 4 KPI section cards (financial / ops / pipeline / roster) ──┐
 *   │                                                                │
 *   ├── Revenue trend (12-month sparkline) ──── Attention list ─────┤
 *   │                                                                │
 *   └────────────────────────────────────────────────────────────────┘
 *
 * Every number on this page is also reachable by drilling into the
 * per-module screens — that's a deliberate property: the dashboard is
 * an aggregator, not a separate source of truth.
 */
export function ExecutiveDashboardPage() {
  return (
    <div className="p-6 lg:p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">
          Executive Dashboard
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Cross-module KPI rollup — financial, operations, pipeline, and
          roster pulses in one place.
        </p>
      </header>

      <div className="space-y-6">
        <PulseGrid />
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <RevenueTrend />
          </div>
          <div className="lg:col-span-1">
            <AttentionRail />
          </div>
        </div>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Pulse grid — four section cards
// ──────────────────────────────────────────────────────────────────────

function PulseGrid() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["executive-dashboard", "summary"],
    queryFn: fetchExecutiveSummary,
    staleTime: 60 * 1000,
  });

  if (isError) {
    return <ErrorBlock message="Couldn't load executive summary." />;
  }
  if (isLoading || !data) {
    return (
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <SkeletonBlock key={i} height="h-44" />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
      <FinancialCard data={data} />
      <OperationsCard data={data} />
      <PipelineCard data={data} />
      <RosterCard data={data} />
    </div>
  );
}

function FinancialCard({ data }: { data: ExecutiveSummary }) {
  const f = data.financial;
  // Color the GP% chip by sign so a loss across the portfolio reads
  // immediately even before the eye scans the number.
  const gpTone =
    f.weighted_gross_profit_pct >= 0.02
      ? "text-primary"
      : f.weighted_gross_profit_pct <= -0.02
        ? "text-critical"
        : "text-warning";

  return (
    <PulseCard
      title="Financial"
      description={`${f.active_jobs} active contracts`}
      Icon={Banknote}
    >
      <BigStat
        value={formatCurrencyCompact(f.total_contract_value)}
        label="Backlog"
      />
      <Row
        label="Revenue earned"
        value={formatCurrencyCompact(f.total_revenue_earned)}
      />
      <Row
        label="Cost to date"
        value={formatCurrencyCompact(f.total_cost_to_date)}
      />
      <Row
        label="Est. gross profit"
        value={formatCurrencyCompact(f.total_estimated_gross_profit)}
        sub={
          <span className={cn("font-mono text-[11px]", gpTone)}>
            {formatPercent(f.weighted_gross_profit_pct)}
          </span>
        }
      />
      <div className="mt-3 flex flex-wrap gap-1.5">
        <Badge variant="outline" className="text-[10px]">
          {f.over_billed_jobs} over-billed
        </Badge>
        <Badge variant="outline" className="text-[10px]">
          {f.under_billed_jobs} under-billed
        </Badge>
        <Badge variant="outline" className="text-[10px]">
          {f.balanced_jobs} balanced
        </Badge>
      </div>
    </PulseCard>
  );
}

function OperationsCard({ data }: { data: ExecutiveSummary }) {
  const o = data.operations;
  return (
    <PulseCard
      title="Operations"
      description={`${o.scheduled_jobs} scheduled jobs`}
      Icon={Construction}
    >
      <BigStat
        value={o.total_equipment.toLocaleString()}
        label="Active equipment"
      />
      <Row
        label="Tickets · 30d"
        value={o.equipment_tickets_30d.toLocaleString()}
      />
      <Row
        label="Revenue · 30d"
        value={formatCurrencyCompact(o.equipment_revenue_30d)}
      />
      <div className="mt-3 grid grid-cols-2 gap-2">
        <MiniChip
          tone={o.jobs_late > 0 ? "critical" : "muted"}
          Icon={AlertOctagon}
          label="Late"
          value={o.jobs_late}
        />
        <MiniChip
          tone={o.jobs_at_risk > 0 ? "warning" : "muted"}
          Icon={Hourglass}
          label="At risk"
          value={o.jobs_at_risk}
        />
      </div>
    </PulseCard>
  );
}

function PipelineCard({ data }: { data: ExecutiveSummary }) {
  const p = data.pipeline;
  return (
    <PulseCard
      title="Pipeline"
      description={`${p.bids_in_pipeline} bids in outlook`}
      Icon={Briefcase}
    >
      <BigStat
        value={formatPercent(p.win_rate_ytd)}
        label="Win rate · YTD"
      />
      <Row
        label="Submitted · YTD"
        value={p.bids_submitted_ytd.toLocaleString()}
      />
      <Row label="Won · YTD" value={p.bids_won_ytd.toLocaleString()} />
      <Row
        label="Upcoming · 30d"
        value={p.upcoming_bids_30d.toLocaleString()}
      />
      <div className="mt-3 flex flex-wrap gap-1.5">
        <Badge variant="outline" className="text-[10px]">
          {p.bids_ready_for_review} ready for review
        </Badge>
        <Badge variant="outline" className="text-[10px]">
          {p.proposals_outstanding} proposals
        </Badge>
      </div>
    </PulseCard>
  );
}

function RosterCard({ data }: { data: ExecutiveSummary }) {
  const r = data.roster;
  return (
    <PulseCard
      title="Roster"
      description="Vendor & asset directory"
      Icon={Users}
    >
      <BigStat value={r.total_vendors.toLocaleString()} label="Vendors" />
      <Row label="Asset master" value={r.total_assets.toLocaleString()} />
      <Row
        label="Retired assets"
        value={r.retired_assets.toLocaleString()}
        sub={
          r.total_assets > 0 ? (
            <span className="font-mono text-[11px] text-muted-foreground">
              {formatPercent(r.retired_assets / r.total_assets)}
            </span>
          ) : undefined
        }
      />
    </PulseCard>
  );
}

// Small primitives used by every card.

function PulseCard({
  title,
  description,
  Icon,
  children,
}: {
  title: string;
  description: string;
  Icon: typeof Banknote;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="space-y-1.5 pb-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-base">{title}</CardTitle>
          <Icon className="h-4 w-4 text-muted-foreground" />
        </div>
        <CardDescription className="text-xs">{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">{children}</CardContent>
    </Card>
  );
}

function BigStat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <div className="font-mono text-2xl font-semibold tabular-nums">
        {value}
      </div>
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: React.ReactNode;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="font-mono text-sm font-semibold tabular-nums">
        {value}
        {sub && <span className="ml-1.5">{sub}</span>}
      </span>
    </div>
  );
}

function MiniChip({
  tone,
  Icon,
  label,
  value,
}: {
  tone: "critical" | "warning" | "muted";
  Icon: typeof AlertOctagon;
  label: string;
  value: number;
}) {
  const toneClass =
    tone === "critical"
      ? "border-critical/30 bg-critical/5 text-critical"
      : tone === "warning"
        ? "border-warning/30 bg-warning/5 text-warning"
        : "border-border bg-muted/30 text-muted-foreground";
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-2 rounded-md border px-2 py-1.5",
        toneClass,
      )}
    >
      <div className="flex items-center gap-1.5 text-[11px] font-medium">
        <Icon className="h-3 w-3" />
        {label}
      </div>
      <span className="font-mono text-sm font-semibold tabular-nums">
        {value}
      </span>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Revenue trend (sparkline)
// ──────────────────────────────────────────────────────────────────────

function RevenueTrend() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["executive-dashboard", "trend", 12],
    queryFn: () => fetchExecutiveTrend(12),
    staleTime: 5 * 60 * 1000,
  });

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <div>
            <CardTitle>Revenue · trailing 12 months</CardTitle>
            <CardDescription>
              Estimate vs. actual from <code>mart_estimate_variance</code>.
            </CardDescription>
          </div>
          <Calendar className="h-4 w-4 text-muted-foreground" />
        </div>
      </CardHeader>
      <CardContent>
        {isError && <ErrorBlock message="Couldn't load revenue trend." />}
        {(isLoading || !data) && !isError && <SkeletonBlock height="h-64" />}
        {data && (
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart
                data={data.months}
                margin={{ top: 8, right: 16, bottom: 8, left: 0 }}
              >
                <defs>
                  <linearGradient id="estFill" x1="0" y1="0" x2="0" y2="1">
                    <stop
                      offset="5%"
                      stopColor="hsl(var(--muted-foreground))"
                      stopOpacity={0.3}
                    />
                    <stop
                      offset="95%"
                      stopColor="hsl(var(--muted-foreground))"
                      stopOpacity={0}
                    />
                  </linearGradient>
                  <linearGradient id="actFill" x1="0" y1="0" x2="0" y2="1">
                    <stop
                      offset="5%"
                      stopColor="hsl(var(--primary))"
                      stopOpacity={0.5}
                    />
                    <stop
                      offset="95%"
                      stopColor="hsl(var(--primary))"
                      stopOpacity={0}
                    />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="hsl(var(--border))"
                />
                <XAxis
                  dataKey="month"
                  tick={{
                    fontSize: 11,
                    fill: "hsl(var(--muted-foreground))",
                  }}
                  stroke="hsl(var(--border))"
                />
                <YAxis
                  tick={{
                    fontSize: 11,
                    fill: "hsl(var(--muted-foreground))",
                  }}
                  stroke="hsl(var(--border))"
                  tickFormatter={(v: number) =>
                    `$${(v / 1_000_000).toFixed(1)}M`
                  }
                />
                <RechartsTooltip
                  cursor={{ fill: "hsl(var(--muted))" }}
                  contentStyle={{
                    background: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  formatter={(v: number, name: string) => [
                    formatCurrencyCompact(v),
                    name === "actual" ? "Actual" : "Estimate",
                  ]}
                />
                <Area
                  type="monotone"
                  dataKey="estimate"
                  stroke="hsl(var(--muted-foreground))"
                  strokeWidth={1.5}
                  strokeDasharray="4 4"
                  fill="url(#estFill)"
                />
                <Area
                  type="monotone"
                  dataKey="actual"
                  stroke="hsl(var(--primary))"
                  strokeWidth={2}
                  fill="url(#actFill)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Attention rail
// ──────────────────────────────────────────────────────────────────────

function AttentionRail() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["executive-dashboard", "attention", 10],
    queryFn: () => fetchExecutiveAttention(10),
    staleTime: 60 * 1000,
  });

  return (
    <Card className="lg:sticky lg:top-6">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Gauge className="h-4 w-4 text-warning" />
          <CardTitle>Needs attention</CardTitle>
        </div>
        <CardDescription>
          Top flagged jobs across margin, schedule, and billing axes.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2.5">
        {isError && <ErrorBlock message="Couldn't load attention list." />}
        {isLoading &&
          !isError &&
          Array.from({ length: 5 }).map((_, i) => (
            <SkeletonBlock key={i} height="h-16" />
          ))}
        {data && data.items.length === 0 && (
          <div className="rounded-md border border-dashed border-border bg-muted/30 p-4 text-center text-xs text-muted-foreground">
            Nothing flagged. The portfolio looks clean.
          </div>
        )}
        {data &&
          data.items.map((item, idx) => (
            <AttentionRow key={`${item.job_id}-${item.kind}-${idx}`} item={item} />
          ))}
      </CardContent>
    </Card>
  );
}

function AttentionRow({ item }: { item: AttentionItem }) {
  const tone = attentionTone(item.kind);
  const Icon = tone.Icon;
  return (
    <div
      className={cn(
        "rounded-lg border p-3",
        tone.borderClass,
        tone.bgClass,
      )}
    >
      <div className="flex items-start gap-2">
        <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", tone.textClass)} />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center justify-between gap-2">
            <p
              className="truncate text-sm font-semibold leading-tight"
              title={item.job}
            >
              {item.job}
            </p>
            <Badge
              variant="outline"
              className={cn("shrink-0 text-[10px]", tone.textClass)}
            >
              {tone.label}
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground">{item.detail}</p>
        </div>
      </div>
    </div>
  );
}

function attentionTone(kind: AttentionKind): {
  Icon: typeof AlertOctagon;
  textClass: string;
  borderClass: string;
  bgClass: string;
  label: string;
} {
  switch (kind) {
    case "loss":
      return {
        Icon: TrendingDown,
        textClass: "text-critical",
        borderClass: "border-critical/30",
        bgClass: "bg-critical/5",
        label: "Loss",
      };
    case "late":
      return {
        Icon: AlertOctagon,
        textClass: "text-critical",
        borderClass: "border-critical/30",
        bgClass: "bg-critical/5",
        label: "Late",
      };
    case "at_risk":
      return {
        Icon: AlertTriangle,
        textClass: "text-warning",
        borderClass: "border-warning/30",
        bgClass: "bg-warning/5",
        label: "At risk",
      };
    case "over_billed":
      return {
        Icon: TrendingUp,
        textClass: "text-warning",
        borderClass: "border-warning/30",
        bgClass: "bg-warning/5",
        label: "Over-billed",
      };
    case "under_billed":
    default:
      return {
        Icon: DollarSign,
        textClass: "text-info",
        borderClass: "border-info/30",
        bgClass: "bg-info/5",
        label: "Under-billed",
      };
  }
}

// ──────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────

function ErrorBlock({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-critical/30 bg-critical/5 p-3 text-sm text-critical">
      <Info className="mr-1 inline h-3.5 w-3.5" />
      {message}
    </div>
  );
}

function SkeletonBlock({ height = "h-24" }: { height?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-muted", height)} />;
}

function formatPercent(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

/** Compact $ format: $1.2M / $850K / $123. Negative wraps in parens. */
function formatCurrencyCompact(n: number): string {
  const abs = Math.abs(n);
  let core: string;
  if (abs >= 1_000_000) {
    core = `$${(abs / 1_000_000).toFixed(2)}M`;
  } else if (abs >= 1_000) {
    core = `$${(abs / 1_000).toFixed(0)}K`;
  } else {
    core = `$${abs.toFixed(0)}`;
  }
  return n < 0 ? `(${core})` : core;
}
