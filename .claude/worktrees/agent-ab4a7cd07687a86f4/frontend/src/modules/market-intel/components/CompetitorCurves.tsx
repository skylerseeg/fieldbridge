import { memo, useCallback, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowDown, ArrowUp, ArrowUpDown, ExternalLink } from "lucide-react";
import {
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

import { useCompetitorCurves } from "../hooks/useCompetitorCurves";
import type { CompetitorCurveRow } from "../api/types";
import { EmptyState } from "./EmptyState";
import type { MonthsBack } from "./ModuleHeader";

/**
 * Competitor curves — slice 2.
 *
 * Three coordinated views over the same dataset:
 *
 *   1. ScatterChart (Recharts):
 *        x = median_rank (1 = always low; right = consistently further)
 *        y = avg_premium_over_low (%)
 *        z = bid_count (dot size; bigger = more bids in the window)
 *        fill = win_rate teal ramp (light = low rate, dark = high)
 *      Click a dot → drilldown Sheet.
 *   2. Sortable Table below the chart, same rows. Each row is a
 *      keyboard-reachable button — chart-by-itself isn't keyboard-
 *      navigable in Recharts, so the table is the canonical
 *      keyboard surface for opening the drilldown. (Brief allows
 *      tab-through dots as nice-to-have.)
 *   3. Side Sheet (right) with the full row + a "View bid history"
 *      action that navigates to `/market-intel/contractor/{slug}`.
 *      That route is NOT yet wired in `routes.tsx` — see the
 *      module README for the Lead handoff.
 *
 * Color discipline: hue + saturation come from `--color-good` (teal);
 * only lightness varies across the 5-stop ramp. Watch coral isn't
 * used in this tab — it'll surface in slice 3 (over-bid markers) and
 * slice 4 (premium-over-low line on the calibration chart).
 */

const MIN_BIDS_FLOOR = 10;

// ── Win-rate teal ramp ──────────────────────────────────────────────
//
// Anchor: hue 173 / saturation 80% comes from `--color-good`
// (defined in src/index.css). Lightness varies from 78% (light) at
// low win rate down to 26% (dark) at high win rate. Stop edges are
// inclusive on the upper bound — `binWinRate` returns the index.
//
// Keep this in sync with the canonical `--color-good` token: if the
// hue changes there, change the leading "173 80%" here.

const TEAL_RAMP: readonly string[] = [
  "hsl(173 80% 78%)", //   ≤ 0.10
  "hsl(173 80% 60%)", //   ≤ 0.20
  "hsl(173 80% 46%)", //   ≤ 0.30
  "hsl(173 80% 36%)", //   ≤ 0.40   matches --color-good DEFAULT
  "hsl(173 80% 26%)", //   > 0.40
] as const;

const RAMP_LABELS: readonly string[] = [
  "≤ 10%",
  "10–20%",
  "20–30%",
  "30–40%",
  "> 40%",
] as const;

function binWinRate(rate: number): number {
  if (rate <= 0.1) return 0;
  if (rate <= 0.2) return 1;
  if (rate <= 0.3) return 2;
  if (rate <= 0.4) return 3;
  return 4;
}

// ── Sort + slug helpers ─────────────────────────────────────────────

type SortField =
  | "contractor_name"
  | "bid_count"
  | "median_rank"
  | "avg_premium_over_low"
  | "win_rate";

type SortDir = "asc" | "desc";

interface SortState {
  field: SortField;
  dir: SortDir;
}

function compare(a: CompetitorCurveRow, b: CompetitorCurveRow, sort: SortState): number {
  const av = a[sort.field];
  const bv = b[sort.field];
  let delta: number;
  if (typeof av === "string" && typeof bv === "string") {
    delta = av.localeCompare(bv);
  } else {
    delta = (av as number) - (bv as number);
  }
  return sort.dir === "asc" ? delta : -delta;
}

/** Slug a contractor name for the detail-route URL. */
function slugifyContractor(name: string): string {
  return name
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

// ── Component ───────────────────────────────────────────────────────

export interface CompetitorCurvesProps {
  states: string[];
  monthsBack: MonthsBack;
}

export default function CompetitorCurves({
  states,
  monthsBack,
}: CompetitorCurvesProps) {
  const { data, isLoading, isError, refetch } = useCompetitorCurves({
    states,
    monthsBack,
    minBids: MIN_BIDS_FLOOR,
  });

  const [sort, setSort] = useState<SortState>({
    field: "bid_count",
    dir: "desc",
  });

  const [selected, setSelected] = useState<CompetitorCurveRow | null>(null);

  const sorted = useMemo(() => {
    if (!data) return [];
    return [...data].sort((a, b) => compare(a, b, sort));
  }, [data, sort]);

  // Recharts-friendly projection — pre-compute the % version of the
  // premium so the y-axis renders in human-readable percent units.
  const chartPoints = useMemo(
    () =>
      sorted.map((row) => ({
        ...row,
        avg_premium_pct: row.avg_premium_over_low * 100,
        ramp: binWinRate(row.win_rate),
      })),
    [sorted],
  );

  // Stabilize callbacks so the memoized ScatterPanel / CompetitorTable
  // / DrilldownSheet only re-render when their data props actually move.
  // toggleSort uses functional setState only — empty deps are correct.
  const toggleSort = useCallback((field: SortField) => {
    setSort((prev) =>
      prev.field === field
        ? { field, dir: prev.dir === "asc" ? "desc" : "asc" }
        : {
            field,
            // Default direction by field — names ascend, numbers descend.
            dir: field === "contractor_name" ? "asc" : "desc",
          },
    );
  }, []);

  // Re-creates only when `sorted` does (which is the same window the
  // chart re-renders anyway, so memoization still pays off elsewhere).
  const handleScatterSelect = useCallback(
    (name: string) => {
      setSelected(
        sorted.find((r) => r.contractor_name === name) ?? null,
      );
    },
    [sorted],
  );

  const handleSheetOpenChange = useCallback((open: boolean) => {
    if (!open) setSelected(null);
  }, []);

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle className="text-base">Competitor curves</CardTitle>
          <p className="text-xs text-muted-foreground">
            Every competitor has a pricing personality. Median rank vs.
            average premium over low, sized by bid count.
          </p>
        </div>
        {data && data.length > 0 && (
          <RampLegend />
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {isError && (
          <EmptyState
            tone="error"
            title="Couldn't load competitor curves."
            description="Pipeline may be paused — try again or check the worker status."
            data-testid="curves-error"
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
          <ScatterSkeleton aria-label="Loading competitor curves" />
        )}

        {!isError && !isLoading && data && data.length === 0 && (
          <EmptyState
            tone="info"
            title="Not enough bid history yet."
            description="Pipeline ingests new awards nightly. Curves appear once at least one contractor has 10+ bids in the selected window."
            data-testid="curves-empty"
          />
        )}

        {!isError && !isLoading && data && data.length > 0 && (
          <>
            <ScatterPanel
              points={chartPoints}
              onSelect={handleScatterSelect}
            />
            <CompetitorTable
              rows={sorted}
              sort={sort}
              onToggleSort={toggleSort}
              onSelect={setSelected}
            />
          </>
        )}
      </CardContent>

      <DrilldownSheet row={selected} onOpenChange={handleSheetOpenChange} />
    </Card>
  );
}

// ── Scatter ─────────────────────────────────────────────────────────

interface ChartPoint extends CompetitorCurveRow {
  avg_premium_pct: number;
  ramp: number;
}

const ScatterPanel = memo(function ScatterPanel({
  points,
  onSelect,
}: {
  points: ChartPoint[];
  onSelect: (contractorName: string) => void;
}) {
  return (
    <figure
      className="space-y-2"
      role="figure"
      aria-label="Competitor curves scatter — median rank versus average premium over low. Dot size indicates bid count; teal saturation indicates win rate."
    >
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 12, right: 16, bottom: 28, left: 8 }}>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="hsl(var(--border))"
            />
            <XAxis
              type="number"
              dataKey="median_rank"
              name="Median rank"
              domain={[1, "dataMax + 0.5"]}
              tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
              stroke="hsl(var(--border))"
              label={{
                value: "Median rank (1 = always low)",
                position: "insideBottom",
                offset: -16,
                style: {
                  fill: "hsl(var(--muted-foreground))",
                  fontSize: 11,
                },
              }}
            />
            <YAxis
              type="number"
              dataKey="avg_premium_pct"
              name="Avg premium"
              tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
              stroke="hsl(var(--border))"
              tickFormatter={(v: number) => `${v.toFixed(0)}%`}
              label={{
                value: "Avg premium over low",
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
            <ZAxis
              type="number"
              dataKey="bid_count"
              name="Bid count"
              range={[60, 420]}
            />
            <RechartsTooltip
              cursor={{ stroke: "hsl(var(--border))", strokeDasharray: "3 3" }}
              contentStyle={{
                background: "hsl(var(--card))",
                border: "1px solid hsl(var(--border))",
                borderRadius: 8,
                fontSize: 12,
                padding: "8px 10px",
              }}
              content={<ScatterTooltip />}
            />
            <Scatter
              data={points}
              onClick={(item) => {
                // Recharts' Scatter onClick yields a `ScatterPointItem`
                // whose `payload` carries the original datum. Pull the
                // contractor_name from there.
                const payload = item?.payload as ChartPoint | undefined;
                if (payload?.contractor_name) onSelect(payload.contractor_name);
              }}
              cursor="pointer"
              isAnimationActive={false}
            >
              {points.map((p) => (
                <Cell
                  key={p.contractor_name}
                  fill={TEAL_RAMP[p.ramp]}
                  stroke="hsl(var(--card))"
                  strokeWidth={1.5}
                />
              ))}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="text-[11px] text-muted-foreground">
        Click a dot — or any row in the table below — to inspect the
        contractor's full bid profile.
      </figcaption>
    </figure>
  );
});

interface RechartsPayloadEntry {
  payload?: ChartPoint;
}

function ScatterTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: RechartsPayloadEntry[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  const p = payload[0]?.payload;
  if (!p) return null;
  return (
    <div className="space-y-1">
      <div className="font-semibold">{p.contractor_name}</div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
        <span className="text-muted-foreground">Median rank</span>
        <span className="text-right font-mono tabular-nums">
          {p.median_rank.toFixed(1)}
        </span>
        <span className="text-muted-foreground">Avg premium</span>
        <span className="text-right font-mono tabular-nums">
          {formatPercent(p.avg_premium_over_low * 100)}
        </span>
        <span className="text-muted-foreground">Win rate</span>
        <span className="text-right font-mono tabular-nums">
          {formatPercent(p.win_rate * 100)}
        </span>
        <span className="text-muted-foreground">Bids</span>
        <span className="text-right font-mono tabular-nums">
          {p.bid_count.toLocaleString()}
        </span>
      </div>
    </div>
  );
}

// ── Table ───────────────────────────────────────────────────────────

interface CompetitorTableProps {
  rows: CompetitorCurveRow[];
  sort: SortState;
  onToggleSort: (field: SortField) => void;
  onSelect: (row: CompetitorCurveRow) => void;
}

const CompetitorTable = memo(function CompetitorTable({
  rows,
  sort,
  onToggleSort,
  onSelect,
}: CompetitorTableProps) {
  return (
    <div className="rounded-lg border border-border">
      <Table>
        <TableHeader>
          <TableRow>
            <SortableHead
              label="Contractor"
              field="contractor_name"
              sort={sort}
              onToggle={onToggleSort}
              align="left"
            />
            <SortableHead
              label="Bids"
              field="bid_count"
              sort={sort}
              onToggle={onToggleSort}
              align="right"
            />
            <SortableHead
              label="Median rank"
              field="median_rank"
              sort={sort}
              onToggle={onToggleSort}
              align="right"
            />
            <SortableHead
              label="Avg premium"
              field="avg_premium_over_low"
              sort={sort}
              onToggle={onToggleSort}
              align="right"
            />
            <SortableHead
              label="Win rate"
              field="win_rate"
              sort={sort}
              onToggle={onToggleSort}
              align="right"
            />
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const ramp = binWinRate(row.win_rate);
            return (
              <TableRow
                key={row.contractor_name}
                tabIndex={0}
                role="button"
                aria-label={`Open ${row.contractor_name} drilldown`}
                onClick={() => onSelect(row)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(row);
                  }
                }}
                className="cursor-pointer hover:bg-muted/50 focus-visible:bg-muted/60 focus-visible:outline-none"
              >
                <TableCell className="font-medium">
                  {row.contractor_name}
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {row.bid_count.toLocaleString()}
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {row.median_rank.toFixed(1)}
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {formatPercent(row.avg_premium_over_low * 100)}
                </TableCell>
                <TableCell className="text-right">
                  <span className="inline-flex items-center gap-2">
                    <span
                      aria-hidden
                      className="inline-block h-2.5 w-2.5 rounded-full"
                      style={{ background: TEAL_RAMP[ramp] }}
                    />
                    <span className="font-mono tabular-nums">
                      {formatPercent(row.win_rate * 100)}
                    </span>
                  </span>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
});

function SortableHead({
  label,
  field,
  sort,
  onToggle,
  align,
}: {
  label: string;
  field: SortField;
  sort: SortState;
  onToggle: (field: SortField) => void;
  align: "left" | "right";
}) {
  const active = sort.field === field;
  const dir = active ? sort.dir : null;
  return (
    <TableHead className={align === "right" ? "text-right" : undefined}>
      <button
        type="button"
        onClick={() => onToggle(field)}
        className={cn(
          "inline-flex items-center gap-1 text-xs font-medium uppercase tracking-wide hover:text-foreground focus-visible:outline-none focus-visible:underline",
          align === "right" && "ml-auto",
        )}
        aria-sort={
          active ? (dir === "asc" ? "ascending" : "descending") : "none"
        }
      >
        {label}
        {dir === "asc" ? (
          <ArrowUp className="h-3 w-3" aria-hidden />
        ) : dir === "desc" ? (
          <ArrowDown className="h-3 w-3" aria-hidden />
        ) : (
          <ArrowUpDown className="h-3 w-3 opacity-40" aria-hidden />
        )}
      </button>
    </TableHead>
  );
}

// ── Drilldown Sheet ─────────────────────────────────────────────────

const DrilldownSheet = memo(function DrilldownSheet({
  row,
  onOpenChange,
}: {
  row: CompetitorCurveRow | null;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const open = row !== null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-md">
        {row && (
          <>
            <SheetHeader className="px-6 pt-6">
              <SheetTitle className="text-lg font-semibold">
                {row.contractor_name}
              </SheetTitle>
              <SheetDescription className="text-xs text-muted-foreground">
                Network-wide bid profile across the active filter window.
              </SheetDescription>
            </SheetHeader>

            <div className="space-y-4 px-6 py-4">
              <DetailGrid row={row} />
              <RampReadout winRate={row.win_rate} />
            </div>

            <SheetFooter className="border-t border-border px-6 py-4">
              <SheetClose asChild>
                <Button variant="outline" size="sm">
                  Close
                </Button>
              </SheetClose>
              <Button
                size="sm"
                className="gap-1"
                onClick={() => {
                  navigate(
                    `/market-intel/contractor/${slugifyContractor(row.contractor_name)}`,
                  );
                }}
              >
                View bid history
                <ExternalLink className="h-3.5 w-3.5" aria-hidden />
              </Button>
            </SheetFooter>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
});

function DetailGrid({ row }: { row: CompetitorCurveRow }) {
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
      <DetailRow label="Bids in window" value={row.bid_count.toLocaleString()} />
      <DetailRow label="Median rank" value={row.median_rank.toFixed(1)} />
      <DetailRow
        label="Avg premium over low"
        value={formatPercent(row.avg_premium_over_low * 100)}
      />
      <DetailRow
        label="Win rate"
        value={formatPercent(row.win_rate * 100)}
      />
    </dl>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-0.5">
      <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="font-mono text-base font-semibold tabular-nums">
        {value}
      </dd>
    </div>
  );
}

function RampReadout({ winRate }: { winRate: number }) {
  const ramp = binWinRate(winRate);
  return (
    <div className="rounded-md border border-border bg-muted/40 p-3">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium text-foreground">Win-rate band</span>
        <Badge variant="mono">{RAMP_LABELS[ramp]}</Badge>
      </div>
      <div className="mt-2 flex items-center gap-1" aria-hidden>
        {TEAL_RAMP.map((color, i) => (
          <span
            key={color}
            className={cn(
              "h-2 flex-1 rounded-full",
              i === ramp ? "ring-2 ring-offset-1 ring-offset-card" : "",
            )}
            style={{
              background: color,
              ...(i === ramp ? { boxShadow: "0 0 0 2px hsl(var(--ring))" } : {}),
            }}
          />
        ))}
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">
        Light teal = low win rate; dark teal = high win rate. Hue and
        saturation come from the canonical <code>--color-good</code> token.
      </p>
    </div>
  );
}

// ── Legend ──────────────────────────────────────────────────────────

const RampLegend = memo(function RampLegend() {
  return (
    <div
      className="flex items-center gap-2 text-[11px] text-muted-foreground"
      aria-label="Win-rate color ramp legend"
    >
      <span className="hidden sm:inline">Win rate</span>
      <div className="flex items-center gap-0.5" aria-hidden>
        {TEAL_RAMP.map((color, i) => (
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

function ScatterSkeleton({ "aria-label": ariaLabel }: { "aria-label": string }) {
  return (
    <div
      role="status"
      aria-busy
      aria-label={ariaLabel}
      className="space-y-3"
      data-testid="curves-loading"
    >
      <div className="h-72 w-full animate-pulse rounded-md bg-muted motion-reduce:animate-none" />
      <div className="h-32 w-full animate-pulse rounded-md bg-muted/60 motion-reduce:animate-none" />
    </div>
  );
}

// ── Helpers ─────────────────────────────────────────────────────────

function formatPercent(n: number): string {
  return `${n.toFixed(1)}%`;
}
