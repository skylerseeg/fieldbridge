import { memo, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronRight, MapPin } from "lucide-react";
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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { useOpportunityGaps } from "../hooks/useOpportunityGaps";
import type { OpportunityRow } from "../api/types";
import { EmptyState } from "./EmptyState";
import type { MonthsBack } from "./ModuleHeader";
import { ScopeMultiSelect } from "./ScopeMultiSelect";

/**
 * Opportunity gaps — slice 3.
 *
 * Two coordinated views over the same dataset:
 *
 *   1. BarChart (left, 2/3 width on lg+):
 *        x = county (ordered by state, then missed_count desc)
 *        y = missed_count
 *        fill = coral ramp by missed_count quantile
 *      Hover shows county + state + avg low bid + scope codes.
 *      Bars are decorative; the right-side list is the keyboard
 *      surface (matches the slice-2 pattern from CompetitorCurves).
 *
 *   2. Top-10 list (right, 1/3 width):
 *      Counties ranked by missed_count desc with avg low bid + scope-
 *      code badges. Each row is a keyboard-reachable link that
 *      navigates to `/market-intel/gap/{state}/{county}`.
 *
 * Filters:
 *   - Scope-code multi-select intersects with the dataset's union
 *     of `top_scope_codes` (default: all selected → no filter
 *     effect; empty → zero rows = explicit empty state).
 *   - Bid-window (250k–5M) and months-back come from the page; they
 *     drive the underlying fetch via the hook.
 *
 * Color discipline: hue + saturation come from `--color-watch`
 * (#F87171, HSL 4 92%); the 5-stop ramp varies only lightness.
 * The 64% lightness stop matches the canonical token. This is the
 * tab where coral makes its first real appearance — high-miss
 * counties are exactly the "watch this" signal coral is meant for.
 */

const DEFAULT_BID_MIN = 250_000;
const DEFAULT_BID_MAX = 5_000_000;

// ── Coral ramp ──────────────────────────────────────────────────────
//
// Anchor: hue 4, saturation 92% — same channels as `--color-watch`
// in src/index.css. Lightness varies 88% (light, low miss count)
// down to 38% (dark, high miss count). Bin edges chosen against the
// observed mock-data distribution (3–24 misses); when real data
// arrives we'll re-bin against the observed quartiles.
//
// Keep this in sync with the canonical `--color-watch` token: if the
// hue changes there, change the leading "4 92%" here.

const CORAL_RAMP: readonly string[] = [
  "hsl(4 92% 88%)", //   ≤  5
  "hsl(4 92% 78%)", //   ≤ 10
  "hsl(4 92% 64%)", //   ≤ 15   matches --color-watch DEFAULT
  "hsl(4 92% 50%)", //   ≤ 20
  "hsl(4 92% 38%)", //   > 20
] as const;

const RAMP_LABELS: readonly string[] = [
  "≤ 5",
  "6–10",
  "11–15",
  "16–20",
  "> 20",
] as const;

function binMissedCount(n: number): number {
  if (n <= 5) return 0;
  if (n <= 10) return 1;
  if (n <= 15) return 2;
  if (n <= 20) return 3;
  return 4;
}

// ── Helpers ─────────────────────────────────────────────────────────

function formatMoney(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (abs >= 10_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toLocaleString()}`;
}

function rowKey(row: OpportunityRow): string {
  return `${row.state}|${row.county ?? ""}`;
}

function rowLabel(row: OpportunityRow): string {
  return row.county ? `${row.county}, ${row.state}` : row.state;
}

// ── Component ───────────────────────────────────────────────────────

export interface OpportunityGapsProps {
  monthsBack: MonthsBack;
}

export default function OpportunityGaps({ monthsBack }: OpportunityGapsProps) {
  const { data, isLoading, isError, refetch } = useOpportunityGaps({
    bidMin: DEFAULT_BID_MIN,
    bidMax: DEFAULT_BID_MAX,
    monthsBack,
  });

  // Scope-code universe: union of every row's top_scope_codes.
  // Brief: "for now, derive from rendered rows' top_scope_codes
  // union". When Vista is wired, swap to a real "VanCon's historical
  // scopes" feed.
  const scopeOptions = useMemo(() => {
    if (!data) return [];
    const set = new Set<string>();
    for (const row of data) {
      for (const code of row.top_scope_codes) set.add(code);
    }
    return [...set].sort();
  }, [data]);

  // Selected scopes default to every code the universe contains.
  // We re-sync whenever the universe changes (filter or new fetch),
  // because `[]` is a meaningful state ("user wants nothing") that
  // we shouldn't accidentally bounce back to "all".
  const [selectedScopes, setSelectedScopes] = useState<string[] | null>(null);
  const effectiveScopes =
    selectedScopes ?? scopeOptions; // null sentinel = "all" until user touches

  const filteredRows = useMemo(() => {
    if (!data) return [];
    const sel = new Set(effectiveScopes);
    if (sel.size === 0) return [];
    return data.filter((row) =>
      row.top_scope_codes.some((code) => sel.has(code)),
    );
  }, [data, effectiveScopes]);

  // Chart points: order by state ASC, then missed_count DESC within
  // state, so the bars visually cluster by state without needing a
  // multi-tier x-axis (Recharts can do that, but readability suffers
  // with 30 ticks).
  const chartPoints = useMemo(
    () =>
      [...filteredRows]
        .sort((a, b) => {
          if (a.state !== b.state) return a.state.localeCompare(b.state);
          return b.missed_count - a.missed_count;
        })
        .map((row) => ({
          ...row,
          label: row.county ?? row.state,
          ramp: binMissedCount(row.missed_count),
        })),
    [filteredRows],
  );

  // Top 10 list: ranked by missed_count DESC.
  const topRows = useMemo(
    () =>
      [...filteredRows]
        .sort((a, b) => b.missed_count - a.missed_count)
        .slice(0, 10),
    [filteredRows],
  );

  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 space-y-0 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <CardTitle className="text-base">Opportunity gaps</CardTitle>
          <p className="text-xs text-muted-foreground">
            Counties where similar-scope work happened but VanCon never bid.
            Top-10 gaps surface the densest opportunities first.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ScopeMultiSelect
            options={scopeOptions}
            value={effectiveScopes}
            onChange={setSelectedScopes}
            id="opportunity-gaps-scope"
          />
          {filteredRows.length > 0 && <CoralLegend />}
        </div>
      </CardHeader>
      <CardContent>
        {isError && (
          <EmptyState
            tone="error"
            title="Couldn't load opportunity gaps."
            description="Pipeline may be paused — try again or check the worker status."
            data-testid="gaps-error"
            action={
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => refetch()}
              >
                Retry
              </Button>
            }
          />
        )}

        {!isError && isLoading && (
          <BarSkeleton aria-label="Loading opportunity gaps" />
        )}

        {!isError && !isLoading && data && data.length === 0 && (
          <EmptyState
            tone="info"
            title="No gaps to surface yet."
            description="Either the bid-network ingest hasn't accumulated enough rows for the selected window, or your filters are too tight."
            data-testid="gaps-empty"
          />
        )}

        {!isError && !isLoading && data && data.length > 0 &&
          filteredRows.length === 0 && (
            <EmptyState
              tone="default"
              title="No gaps match the active scope filter."
              description="Re-enable scope codes in the filter above, or click 'All' to reset."
              data-testid="gaps-no-match"
              action={
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setSelectedScopes(scopeOptions)}
                >
                  Reset filter
                </Button>
              }
            />
          )}

        {!isError && !isLoading && filteredRows.length > 0 && (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <BarPanel points={chartPoints} />
            </div>
            <div>
              <TopList rows={topRows} />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Bar chart ───────────────────────────────────────────────────────

interface ChartPoint extends OpportunityRow {
  label: string;
  ramp: number;
}

const BarPanel = memo(function BarPanel({
  points,
}: {
  points: ChartPoint[];
}) {
  return (
    <figure
      className="space-y-2"
      role="figure"
      aria-label="Opportunity gaps bar chart — county on x axis, missed bid count on y axis. Bars grouped by state, coral fill saturates with miss count."
    >
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={points}
            margin={{ top: 8, right: 12, bottom: 56, left: 0 }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="hsl(var(--border))"
            />
            <XAxis
              dataKey="label"
              interval={0}
              tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
              stroke="hsl(var(--border))"
              angle={-35}
              textAnchor="end"
              height={56}
            />
            <YAxis
              allowDecimals={false}
              tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
              stroke="hsl(var(--border))"
              label={{
                value: "Missed bids",
                angle: -90,
                position: "insideLeft",
                offset: 12,
                style: {
                  fill: "hsl(var(--muted-foreground))",
                  fontSize: 11,
                  textAnchor: "middle",
                },
              }}
            />
            <RechartsTooltip
              cursor={{ fill: "hsl(var(--muted))" }}
              contentStyle={{
                background: "hsl(var(--card))",
                border: "1px solid hsl(var(--border))",
                borderRadius: 8,
                fontSize: 12,
                padding: "8px 10px",
              }}
              content={<BarTooltip />}
            />
            <Bar
              dataKey="missed_count"
              radius={[4, 4, 0, 0]}
              isAnimationActive={false}
            >
              {points.map((p) => (
                <Cell key={rowKey(p)} fill={CORAL_RAMP[p.ramp]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="text-[11px] text-muted-foreground">
        Bars cluster by state (alphabetical), then sort by miss count
        within each state. Use the list on the right for keyboard navigation.
      </figcaption>
    </figure>
  );
});

interface TooltipPayloadEntry {
  payload?: ChartPoint;
}

function BarTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: TooltipPayloadEntry[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  const p = payload[0]?.payload;
  if (!p) return null;
  return (
    <div className="space-y-1 min-w-[180px]">
      <div className="flex items-center justify-between gap-3">
        <span className="font-semibold">{rowLabel(p)}</span>
        <Badge variant="mono">{p.state}</Badge>
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
        <span className="text-muted-foreground">Missed</span>
        <span className="text-right font-mono tabular-nums">
          {p.missed_count.toLocaleString()}
        </span>
        <span className="text-muted-foreground">Avg low bid</span>
        <span className="text-right font-mono tabular-nums">
          {formatMoney(p.avg_low_bid)}
        </span>
      </div>
      {p.top_scope_codes.length > 0 && (
        <div className="pt-1.5">
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Scope codes
          </span>
          <div className="mt-0.5 flex flex-wrap gap-1">
            {p.top_scope_codes.map((code) => (
              <span
                key={code}
                className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-foreground"
              >
                {code}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Top-10 list ─────────────────────────────────────────────────────

const TopList = memo(function TopList({
  rows,
}: {
  rows: OpportunityRow[];
}) {
  const navigate = useNavigate();
  return (
    <section
      className="rounded-lg border border-border bg-card"
      aria-label="Top opportunity gaps ranked by missed count"
    >
      <header className="border-b border-border px-4 py-3">
        <h3 className="text-sm font-semibold">Top {rows.length} gaps</h3>
        <p className="text-[11px] text-muted-foreground">
          Click a row for the full bid history.
        </p>
      </header>
      <ol className="divide-y divide-border">
        {rows.map((row, idx) => {
          const ramp = binMissedCount(row.missed_count);
          return (
            <li key={rowKey(row)}>
              <button
                type="button"
                onClick={() =>
                  navigate(
                    `/market-intel/gap/${row.state}/${encodeURIComponent(row.county ?? "")}`,
                  )
                }
                className={cn(
                  "group flex w-full items-center gap-3 px-4 py-3 text-left",
                  "hover:bg-muted/50 focus-visible:bg-muted/60 focus-visible:outline-none",
                )}
                aria-label={`Open ${rowLabel(row)} bid history — ${row.missed_count} missed bids`}
              >
                <span
                  className="font-mono text-xs text-muted-foreground tabular-nums"
                  aria-hidden
                >
                  {String(idx + 1).padStart(2, "0")}
                </span>
                <span
                  aria-hidden
                  className="inline-block h-2.5 w-2.5 rounded-full"
                  style={{ background: CORAL_RAMP[ramp] }}
                />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5 text-sm font-medium">
                    <MapPin className="h-3 w-3 text-muted-foreground" aria-hidden />
                    {rowLabel(row)}
                  </span>
                  <span className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                    <span>Avg {formatMoney(row.avg_low_bid)}</span>
                    {row.top_scope_codes.slice(0, 3).map((code) => (
                      <Badge
                        key={code}
                        variant="mono"
                        className="text-[10px]"
                      >
                        {code}
                      </Badge>
                    ))}
                  </span>
                </span>
                <span className="flex flex-col items-end gap-0.5">
                  <span className="font-mono text-base font-semibold tabular-nums">
                    {row.missed_count}
                  </span>
                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    missed
                  </span>
                </span>
                <ChevronRight
                  className="h-4 w-4 text-muted-foreground/40 group-hover:text-muted-foreground"
                  aria-hidden
                />
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
});

// ── Legend ──────────────────────────────────────────────────────────

const CoralLegend = memo(function CoralLegend() {
  return (
    <div
      className="flex items-center gap-2 text-[11px] text-muted-foreground"
      aria-label="Missed-count color ramp legend"
    >
      <span className="hidden sm:inline">Misses</span>
      <div className="flex items-center gap-0.5" aria-hidden>
        {CORAL_RAMP.map((color, i) => (
          <span
            key={color}
            title={RAMP_LABELS[i]}
            className="h-2 w-5 first:rounded-l-full last:rounded-r-full"
            style={{ background: color }}
          />
        ))}
      </div>
      <span className="hidden sm:inline">low → high</span>
    </div>
  );
});

// ── Skeleton ────────────────────────────────────────────────────────

function BarSkeleton({ "aria-label": ariaLabel }: { "aria-label": string }) {
  return (
    <div
      role="status"
      aria-busy
      aria-label={ariaLabel}
      data-testid="gaps-loading"
      className="grid grid-cols-1 gap-3 lg:grid-cols-3"
    >
      <div className="h-72 w-full animate-pulse rounded-md bg-muted motion-reduce:animate-none lg:col-span-2" />
      <div className="h-72 w-full animate-pulse rounded-md bg-muted/60 motion-reduce:animate-none" />
    </div>
  );
}
