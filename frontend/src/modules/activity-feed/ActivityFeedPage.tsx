import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  Filter,
  Info,
  XCircle,
} from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import {
  fetchActivityFeed,
  fetchActivitySummary,
  type ActivityEvent,
  type ActivityKind,
  type ActivitySeverity,
} from "./activity-feed-api";

/**
 * Activity Feed — cross-source event stream.
 *
 * Backend merges three pre-existing event tables:
 *   - ingest_log    (Excel → mart ingest runs)
 *   - usage_events  (Claude API calls, with per-agent attribution)
 *   - llm_insights  (cached Phase-6 recommendation payloads)
 *
 * Layout mirrors the page header: tile strip up top, filter row, then
 * a scrollable feed sorted by (severity desc, occurred_at desc).
 *
 * "User actions" are deliberately deferred — `users.last_login` only
 * stores the most recent login per user, not a history. A future
 * commit can introduce a proper `user_actions` table; the schema
 * already has the generic `actor` / `entity_ref` fields ready for it.
 */
export function ActivityFeedPage() {
  const [kind, setKind] = useState<ActivityKind | "all">("all");
  const [severity, setSeverity] = useState<ActivitySeverity | "all">("all");

  return (
    <div className="p-6 lg:p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Activity Feed</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Agent events and ingest runs — severity-ranked, trailing 30 days.
        </p>
      </header>

      <div className="space-y-6">
        <SummaryTiles />

        <FilterBar
          kind={kind}
          severity={severity}
          onKindChange={setKind}
          onSeverityChange={setSeverity}
        />

        <FeedList kind={kind} severity={severity} />
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Tile strip
// ──────────────────────────────────────────────────────────────────────

function SummaryTiles() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["activity-feed", "summary"],
    queryFn: () => fetchActivitySummary(),
    staleTime: 60 * 1000,
  });

  if (isError) {
    return <ErrorBlock message="Couldn't load activity summary." />;
  }
  if (isLoading || !data) {
    return (
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <SkeletonBlock key={i} height="h-24" />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
      <Tile
        Icon={Activity}
        label="Total events"
        value={data.total}
        sub="Trailing 30 days"
      />
      <Tile
        Icon={Activity}
        label="Last 24 hours"
        value={data.last_24h}
        accent="info"
      />
      <Tile
        Icon={Activity}
        label="Last 7 days"
        value={data.last_7d}
        accent="info"
      />
      <Tile
        Icon={AlertOctagon}
        label="Critical"
        value={data.by_severity.critical}
        accent="critical"
      />
      <Tile
        Icon={AlertTriangle}
        label="Warning"
        value={data.by_severity.warning}
        accent="warning"
      />
      <Tile
        Icon={CheckCircle2}
        label="Info"
        value={data.by_severity.info}
        accent="info"
      />
    </div>
  );
}

function Tile({
  Icon,
  label,
  value,
  sub,
  accent,
}: {
  Icon: typeof Activity;
  label: string;
  value: number;
  sub?: string;
  accent?: "critical" | "warning" | "info";
}) {
  const accentClass =
    accent === "critical"
      ? "text-critical"
      : accent === "warning"
        ? "text-warning"
        : accent === "info"
          ? "text-info"
          : "text-foreground";
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {label}
        </CardTitle>
        <Icon className={cn("h-4 w-4", accentClass)} />
      </CardHeader>
      <CardContent>
        <div className={cn("text-2xl font-semibold tabular-nums", accentClass)}>
          {value.toLocaleString()}
        </div>
        {sub ? (
          <p className="text-xs text-muted-foreground">{sub}</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Filter bar
// ──────────────────────────────────────────────────────────────────────

const KIND_OPTIONS: Array<{ value: ActivityKind | "all"; label: string }> = [
  { value: "all", label: "All kinds" },
  { value: "ingest_ok", label: "Ingest — ok" },
  { value: "ingest_partial", label: "Ingest — partial" },
  { value: "ingest_failed", label: "Ingest — failed" },
  { value: "agent_call", label: "Agent call" },
  { value: "insight_generated", label: "Insight cached" },
];

const SEVERITY_OPTIONS: Array<{
  value: ActivitySeverity | "all";
  label: string;
}> = [
  { value: "all", label: "All severities" },
  { value: "critical", label: "Critical" },
  { value: "warning", label: "Warning" },
  { value: "info", label: "Info" },
];

function FilterBar({
  kind,
  severity,
  onKindChange,
  onSeverityChange,
}: {
  kind: ActivityKind | "all";
  severity: ActivitySeverity | "all";
  onKindChange: (k: ActivityKind | "all") => void;
  onSeverityChange: (s: ActivitySeverity | "all") => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Filter className="h-3.5 w-3.5" />
        Filters
      </div>
      <select
        value={kind}
        onChange={(e) => onKindChange(e.target.value as ActivityKind | "all")}
        className="h-8 rounded-md border border-input bg-background px-2 text-sm"
      >
        {KIND_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <select
        value={severity}
        onChange={(e) =>
          onSeverityChange(e.target.value as ActivitySeverity | "all")
        }
        className="h-8 rounded-md border border-input bg-background px-2 text-sm"
      >
        {SEVERITY_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Feed list
// ──────────────────────────────────────────────────────────────────────

function FeedList({
  kind,
  severity,
}: {
  kind: ActivityKind | "all";
  severity: ActivitySeverity | "all";
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["activity-feed", "events", kind, severity],
    queryFn: () =>
      fetchActivityFeed({
        topN: 100,
        kind: kind === "all" ? undefined : kind,
        severity: severity === "all" ? undefined : severity,
      }),
    staleTime: 60 * 1000,
  });

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Recent activity</CardTitle>
            <CardDescription>
              Sorted by severity, then most recent first.
            </CardDescription>
          </div>
          {data ? (
            <Badge variant="mono">
              {data.total_returned.toLocaleString()} of{" "}
              {data.total_matching.toLocaleString()}
            </Badge>
          ) : null}
        </div>
      </CardHeader>
      <CardContent>
        {isError ? (
          <ErrorBlock message="Couldn't load the activity feed." />
        ) : isLoading || !data ? (
          <div className="space-y-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <SkeletonBlock key={i} height="h-14" />
            ))}
          </div>
        ) : data.items.length === 0 ? (
          <EmptyBlock />
        ) : (
          <ul className="divide-y divide-border">
            {data.items.map((event) => (
              <li key={event.id}>
                <FeedRow event={event} />
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function FeedRow({ event }: { event: ActivityEvent }) {
  const sev = severityStyle(event.severity);
  const kindMeta = kindStyle(event.kind);
  const occurred = useMemo(() => formatRelative(event.occurred_at), [
    event.occurred_at,
  ]);

  return (
    <div className="flex items-start gap-3 py-3">
      <div
        className={cn(
          "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border",
          sev.borderClass,
          sev.bgClass,
        )}
      >
        <sev.Icon className={cn("h-4 w-4", sev.textClass)} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Badge
            variant="mono"
            className={cn("uppercase tracking-wide", kindMeta.badgeClass)}
          >
            {kindMeta.label}
          </Badge>
          {event.actor ? (
            <span className="font-medium text-foreground">{event.actor}</span>
          ) : null}
          {event.entity_ref ? (
            <span className="text-muted-foreground">· {event.entity_ref}</span>
          ) : null}
          <span className="ml-auto text-xs text-muted-foreground">
            {occurred}
          </span>
        </div>
        <p className="mt-1 text-sm text-foreground">{event.summary}</p>
      </div>
    </div>
  );
}

function EmptyBlock() {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
      <Activity className="h-6 w-6" />
      No matching events in the trailing 30 days.
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Style + format helpers
// ──────────────────────────────────────────────────────────────────────

function severityStyle(s: ActivitySeverity) {
  switch (s) {
    case "critical":
      return {
        Icon: XCircle,
        textClass: "text-critical",
        borderClass: "border-critical/30",
        bgClass: "bg-critical/10",
      };
    case "warning":
      return {
        Icon: AlertTriangle,
        textClass: "text-warning",
        borderClass: "border-warning/30",
        bgClass: "bg-warning/10",
      };
    case "info":
    default:
      return {
        Icon: CheckCircle2,
        textClass: "text-info",
        borderClass: "border-info/30",
        bgClass: "bg-info/10",
      };
  }
}

function kindStyle(k: ActivityKind): {
  label: string;
  badgeClass: string;
} {
  switch (k) {
    case "ingest_ok":
      return { label: "Ingest", badgeClass: "" };
    case "ingest_partial":
      return { label: "Ingest · partial", badgeClass: "" };
    case "ingest_failed":
      return { label: "Ingest · failed", badgeClass: "" };
    case "agent_call":
      return { label: "Agent", badgeClass: "" };
    case "insight_generated":
      return { label: "Insight", badgeClass: "" };
    default:
      return { label: String(k), badgeClass: "" };
  }
}

/** "5m ago", "3h ago", "2d ago", "Apr 11". */
function formatRelative(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const diff = Date.now() - t;
  const mins = Math.round(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

// ──────────────────────────────────────────────────────────────────────
// Inline helpers
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
