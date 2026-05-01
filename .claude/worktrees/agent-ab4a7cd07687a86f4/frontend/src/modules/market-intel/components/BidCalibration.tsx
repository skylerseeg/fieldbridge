import { memo, useMemo } from "react";
import { Info } from "lucide-react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

import { useBidCalibration } from "../hooks/useBidCalibration";
import type { CalibrationPoint } from "../api/types";
import { EmptyState } from "./EmptyState";

/**
 * Bid calibration — slice 4. Brief-closer.
 *
 * Two coordinated views over VanCon's quarterly self-comparison:
 *
 *   1. Dual-axis ComposedChart (Recharts):
 *        x = quarter (last 8, ascending)
 *        Bars (gray, left axis):    bids_submitted
 *        Line 1 (--color-good, left axis): wins
 *        Line 2 (--color-watch, right axis %): pct_above_low * 100
 *      Annotation above the chart locks the brief copy verbatim.
 *
 *   2. Calibration Table below:
 *        Quarter · Bids · Wins · Win rate · Avg rank · Pct above low
 *      The most-recent-quarter row carries `data-current="true"` and
 *      a subtle background — no separate component, just a class.
 *
 * Tenant scope: pinned to "van con" since this branch ships for
 * VanCon's own seat. Multi-tenant overlays are v3 (see
 * `docs/market-intel.md`).
 */

const VANCON_NAME_MATCH = "van con";

export default function BidCalibration() {
  const { data, isLoading, isError, refetch } = useBidCalibration({
    contractorNameMatch: VANCON_NAME_MATCH,
  });

  // Sort quarters ascending so the chart x-axis runs left → right
  // chronologically. Most-recent-quarter highlighting reads the last
  // row of the sorted set.
  const sorted = useMemo(() => {
    if (!data) return [];
    return [...data].sort((a, b) => a.quarter.localeCompare(b.quarter));
  }, [data]);

  const chartPoints = useMemo(
    () =>
      sorted.map((row) => ({
        ...row,
        // Pre-compute to keep the y-axis tick formatter simple.
        pct_above_low_pct:
          row.pct_above_low === null ? null : row.pct_above_low * 100,
        label: formatQuarterLabel(row.quarter),
      })),
    [sorted],
  );

  const mostRecentQuarter = sorted.length
    ? sorted[sorted.length - 1].quarter
    : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Bid calibration</CardTitle>
        <p className="text-xs text-muted-foreground">
          Quarterly self-comparison vs. the low bid. Watch wins and the
          premium-over-low move together — sharper pricing pulls both lines
          in the right direction.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {isError && (
          <EmptyState
            tone="error"
            title="Couldn't load bid calibration."
            description="Pipeline may be paused — try again or check the worker status."
            data-testid="calibration-error"
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
          <ComposedSkeleton aria-label="Loading bid calibration" />
        )}

        {!isError && !isLoading && data && data.length === 0 && (
          <EmptyState
            tone="info"
            title="No calibration data yet."
            description="Calibration appears once VanCon's bid history syncs and at least one quarter of public bid results lands in the window."
            data-testid="calibration-empty"
          />
        )}

        {!isError && !isLoading && chartPoints.length > 0 && (
          <>
            <Annotation />
            <ChartPanel points={chartPoints} />
            <CalibrationTable
              rows={sorted}
              currentQuarter={mostRecentQuarter}
            />
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── Annotation ──────────────────────────────────────────────────────

const Annotation = memo(function Annotation() {
  // Brief copy locked verbatim — including the period after the
  // first sentence, the period after the second, and the lack of an
  // Oxford-style joiner. The vitest assertion in slice 4 checks this
  // exactly.
  return (
    <div
      className="flex items-start gap-2 rounded-md border border-border bg-muted/40 p-3 text-xs text-muted-foreground"
      role="note"
      data-testid="calibration-annotation"
    >
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-info" aria-hidden />
      <p>
        Lower coral = sharper pricing. Higher teal = more wins. Watch them
        move together.
      </p>
    </div>
  );
});

// ── Chart ───────────────────────────────────────────────────────────

interface ChartPoint extends CalibrationPoint {
  pct_above_low_pct: number | null;
  label: string;
}

const ChartPanel = memo(function ChartPanel({
  points,
}: {
  points: ChartPoint[];
}) {
  return (
    <figure
      className="space-y-2"
      role="figure"
      aria-label="Bid calibration composed chart — quarters on x axis. Gray bars: bids submitted. Teal line on left axis: wins. Coral line on right axis: percent above low."
    >
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={points}
            margin={{ top: 12, right: 24, bottom: 8, left: 8 }}
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
              yAxisId="left"
              allowDecimals={false}
              tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
              stroke="hsl(var(--border))"
              label={{
                value: "Bids · wins",
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
            <YAxis
              yAxisId="right"
              orientation="right"
              tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
              stroke="hsl(var(--border))"
              tickFormatter={(v: number) => `${v.toFixed(0)}%`}
              label={{
                value: "% above low",
                angle: 90,
                position: "insideRight",
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
              content={<ComposedTooltip />}
            />
            <Legend
              verticalAlign="top"
              height={28}
              iconSize={10}
              wrapperStyle={{ fontSize: 11 }}
            />
            <Bar
              yAxisId="left"
              dataKey="bids_submitted"
              name="Bids submitted"
              fill="hsl(var(--muted-foreground))"
              fillOpacity={0.35}
              radius={[4, 4, 0, 0]}
              isAnimationActive={false}
            />
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="wins"
              name="Wins"
              stroke="hsl(var(--color-good))"
              strokeWidth={2}
              dot={{ r: 3, fill: "hsl(var(--color-good))" }}
              activeDot={{ r: 5 }}
              isAnimationActive={false}
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="pct_above_low_pct"
              name="% above low"
              stroke="hsl(var(--color-watch))"
              strokeWidth={2}
              strokeDasharray="4 3"
              dot={{ r: 3, fill: "hsl(var(--color-watch))" }}
              activeDot={{ r: 5 }}
              connectNulls
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="text-[11px] text-muted-foreground">
        Bars: bids submitted (left axis). Teal line: wins (left axis).
        Coral dashed line: percent above the winning bid (right axis).
      </figcaption>
    </figure>
  );
});

interface TooltipPayloadEntry {
  payload?: ChartPoint;
}

function ComposedTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: TooltipPayloadEntry[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  const p = payload[0]?.payload;
  if (!p) return null;
  const winRate = p.bids_submitted > 0 ? p.wins / p.bids_submitted : 0;
  return (
    <div className="space-y-1 min-w-[180px]">
      <div className="font-semibold">{p.label}</div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
        <span className="text-muted-foreground">Bids</span>
        <span className="text-right font-mono tabular-nums">
          {p.bids_submitted.toLocaleString()}
        </span>
        <span className="text-muted-foreground">Wins</span>
        <span className="text-right font-mono tabular-nums">
          {p.wins.toLocaleString()}
        </span>
        <span className="text-muted-foreground">Win rate</span>
        <span className="text-right font-mono tabular-nums">
          {(winRate * 100).toFixed(1)}%
        </span>
        <span className="text-muted-foreground">Avg rank</span>
        <span className="text-right font-mono tabular-nums">
          {p.avg_rank.toFixed(1)}
        </span>
        <span className="text-muted-foreground">% above low</span>
        <span className="text-right font-mono tabular-nums">
          {p.pct_above_low === null
            ? "—"
            : `${(p.pct_above_low * 100).toFixed(1)}%`}
        </span>
      </div>
    </div>
  );
}

// ── Table ───────────────────────────────────────────────────────────

const CalibrationTable = memo(function CalibrationTable({
  rows,
  currentQuarter,
}: {
  rows: CalibrationPoint[];
  currentQuarter: string | null;
}) {
  // Display order: most-recent at the top so the row that carries
  // `data-current="true"` is also the first thing the user reads.
  const display = useMemo(() => [...rows].reverse(), [rows]);

  return (
    <div className="rounded-lg border border-border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Quarter</TableHead>
            <TableHead className="text-right">Bids</TableHead>
            <TableHead className="text-right">Wins</TableHead>
            <TableHead className="text-right">Win rate</TableHead>
            <TableHead className="text-right">Avg rank</TableHead>
            <TableHead className="text-right">% above low</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {display.map((row) => {
            const isCurrent = row.quarter === currentQuarter;
            const winRate =
              row.bids_submitted > 0 ? row.wins / row.bids_submitted : 0;
            return (
              <TableRow
                key={row.quarter}
                data-current={isCurrent || undefined}
                aria-current={isCurrent ? "page" : undefined}
                className={cn(isCurrent && "bg-muted/40 font-medium")}
              >
                <TableCell className="font-mono">
                  {formatQuarterLabel(row.quarter)}
                  {isCurrent && (
                    <span className="ml-2 rounded-full bg-info/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-info">
                      Current
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {row.bids_submitted.toLocaleString()}
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {row.wins.toLocaleString()}
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {(winRate * 100).toFixed(1)}%
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {row.avg_rank.toFixed(1)}
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {row.pct_above_low === null
                    ? "—"
                    : `${(row.pct_above_low * 100).toFixed(1)}%`}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
});

// ── Skeleton ────────────────────────────────────────────────────────

function ComposedSkeleton({
  "aria-label": ariaLabel,
}: {
  "aria-label": string;
}) {
  return (
    <div
      role="status"
      aria-busy
      aria-label={ariaLabel}
      data-testid="calibration-loading"
      className="space-y-3"
    >
      <div className="h-72 w-full animate-pulse rounded-md bg-muted motion-reduce:animate-none" />
      <div className="h-32 w-full animate-pulse rounded-md bg-muted/60 motion-reduce:animate-none" />
    </div>
  );
}

// ── Helpers ─────────────────────────────────────────────────────────

/**
 * Format an ISO quarter date (YYYY-MM-DD, first day of quarter)
 * into a compact axis label like `Q1 '26`.
 *
 * Wire format: backend always sends the first day of the quarter
 * — `2026-01-01` for Q1, `2026-04-01` for Q2, `2026-07-01` for Q3,
 * `2026-10-01` for Q4. Anything else falls back to the raw ISO
 * string so we don't silently mis-label.
 */
function formatQuarterLabel(quarter: string): string {
  const match = /^(\d{4})-(\d{2})-\d{2}$/.exec(quarter);
  if (!match) return quarter;
  const [, year, month] = match;
  const monthNum = Number(month);
  const q =
    monthNum === 1
      ? 1
      : monthNum === 4
        ? 2
        : monthNum === 7
          ? 3
          : monthNum === 10
            ? 4
            : null;
  if (q === null) return quarter;
  return `Q${q} '${year.slice(2)}`;
}
