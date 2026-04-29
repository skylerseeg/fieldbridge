import { useMemo } from "react";
import {
  AlertTriangle,
  Hash,
  Target,
  TrendingDown,
  Users,
} from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { useBidCalibration } from "../hooks/useBidCalibration";
import { useCompetitorCurves } from "../hooks/useCompetitorCurves";
import type { CalibrationPoint, CompetitorCurveRow } from "../api/types";
import type { MonthsBack } from "./ModuleHeader";

/**
 * Four-tile KPI strip atop the Market Intel page.
 *
 * Per the brief:
 *   1. Bid events tracked   — count, last `months_back` months
 *   2. Active competitors    — distinct contractors with ≥10 bids
 *   3. VanCon win rate       — % of bids submitted that won
 *   4. Median premium over low — % VanCon's losing bids ran above
 *      the winner
 *
 * KPIs 3 and 4 derive from the calibration query (same data the
 * Bid calibration tab uses). KPIs 1 and 2 derive from competitor
 * curves. We co-locate the queries here so the KPI strip can render
 * before the user clicks into a tab — TanStack will dedupe with the
 * tab-level fetches via shared query keys.
 *
 * Loading: skeleton boxes — never spinners on KPI cards (brief).
 * Error:   the strip degrades to "—" per tile rather than blocking
 *          the rest of the page; an inline banner above the strip
 *          (rendered by MarketIntelPage) carries the explicit error.
 */

const MIN_BIDS_FLOOR = 10;
const VANCON_NAME_MATCH = "van con";

export interface KpiStripProps {
  states: string[];
  monthsBack: MonthsBack;
}

export function KpiStrip({ states, monthsBack }: KpiStripProps) {
  // Both queries are also driven by their respective tabs; same
  // query keys → shared cache → no double-fetch.
  const curves = useCompetitorCurves({
    states,
    monthsBack,
    minBids: MIN_BIDS_FLOOR,
  });
  const calibration = useBidCalibration({
    contractorNameMatch: VANCON_NAME_MATCH,
  });

  const tiles = useMemo(
    () => buildTiles(curves.data, calibration.data, monthsBack),
    [curves.data, calibration.data, monthsBack],
  );

  const isLoading = curves.isLoading || calibration.isLoading;

  return (
    <div
      className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4"
      aria-label="Market Intel summary KPIs"
    >
      {tiles.map((tile) => (
        <KpiCard
          key={tile.key}
          title={tile.title}
          value={tile.value}
          sub={tile.sub}
          Icon={tile.Icon}
          accent={tile.accent}
          loading={isLoading}
        />
      ))}
    </div>
  );
}

// ── Tile shape ──────────────────────────────────────────────────────

type TileAccent = "info" | "primary" | "warning" | "muted";

interface Tile {
  key: string;
  title: string;
  value: string;
  sub: string;
  Icon: typeof Hash;
  accent: TileAccent;
}

function buildTiles(
  curves: CompetitorCurveRow[] | undefined,
  calibration: CalibrationPoint[] | undefined,
  monthsBack: MonthsBack,
): Tile[] {
  // Tile 1 — Bid events tracked.
  // Pipeline doesn't yet expose a network-wide event count; until then
  // we display sum(bid_count) labelled honestly as "bid lines". Once
  // the backend ships a /summary endpoint we'll swap to a true event
  // count. PROPOSED_CHANGES tracks this for the Backend worker.
  const bidLines = curves
    ? curves.reduce((acc, row) => acc + row.bid_count, 0)
    : null;

  // Tile 2 — Active competitors (already filtered server-side to
  // ≥10 bids via the min_bids param the curves hook sends).
  const competitorCount = curves ? curves.length : null;

  // Tile 3 — VanCon win rate across the calibration window.
  const winRate = calibration
    ? computeWinRate(calibration)
    : null;

  // Tile 4 — Median premium over low across quarters with data.
  const medianPremium = calibration
    ? computeMedianPremium(calibration)
    : null;

  return [
    {
      key: "bid_events",
      title: "Bid events tracked",
      value: bidLines === null ? "—" : formatCount(bidLines),
      sub: `Last ${monthsBack} months · bid lines`,
      Icon: Hash,
      accent: "info",
    },
    {
      key: "competitors",
      title: "Active competitors",
      value:
        competitorCount === null ? "—" : formatCount(competitorCount),
      sub: `${MIN_BIDS_FLOOR}+ bids in window`,
      Icon: Users,
      accent: "info",
    },
    {
      key: "win_rate",
      title: "VanCon win rate",
      value: winRate === null ? "—" : formatPercent(winRate * 100),
      sub: calibration?.length
        ? `${sumWins(calibration).toLocaleString()} wins of ${sumBids(calibration).toLocaleString()}`
        : "no calibration data",
      Icon: Target,
      accent: winRate !== null && winRate >= 0.2 ? "primary" : "info",
    },
    {
      key: "median_premium",
      title: "Median premium over low",
      value: medianPremium === null ? "—" : formatPercent(medianPremium * 100),
      sub: "across quarters",
      Icon:
        medianPremium !== null && medianPremium > 0.05
          ? AlertTriangle
          : TrendingDown,
      accent:
        medianPremium === null
          ? "muted"
          : medianPremium > 0.05
            ? "warning"
            : "primary",
    },
  ];
}

// ── Card ────────────────────────────────────────────────────────────

interface KpiCardProps {
  title: string;
  value: string;
  sub: string;
  Icon: typeof Hash;
  accent: TileAccent;
  loading: boolean;
}

const accentStyles: Record<
  TileAccent,
  { border: string; bg: string; text: string }
> = {
  info: {
    border: "border-l-info",
    bg: "bg-info/10",
    text: "text-info",
  },
  primary: {
    border: "border-l-primary",
    bg: "bg-primary/10",
    text: "text-primary",
  },
  warning: {
    border: "border-l-warning",
    bg: "bg-warning/10",
    text: "text-warning",
  },
  muted: {
    border: "border-l-border",
    bg: "bg-muted",
    text: "text-muted-foreground",
  },
};

function KpiCard({ title, value, sub, Icon, accent, loading }: KpiCardProps) {
  const s = accentStyles[accent];
  return (
    <Card
      className={cn("border-l-4", s.border)}
      aria-busy={loading || undefined}
    >
      <CardContent className="flex flex-col gap-2 p-4">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-muted-foreground">
            {title}
          </span>
          <div
            className={cn(
              "flex h-7 w-7 items-center justify-center rounded-md",
              s.bg,
            )}
            aria-hidden
          >
            <Icon className={cn("h-3.5 w-3.5", s.text)} />
          </div>
        </div>
        {loading ? (
          <div
            className="mt-1 h-7 w-24 animate-pulse rounded-md bg-muted motion-reduce:animate-none"
            aria-hidden
          />
        ) : (
          <div className="font-mono text-2xl font-semibold tabular-nums">
            {value}
          </div>
        )}
        {loading ? (
          <div
            className="h-3 w-32 animate-pulse rounded-md bg-muted/60 motion-reduce:animate-none"
            aria-hidden
          />
        ) : (
          <span className="text-[11px] text-muted-foreground">{sub}</span>
        )}
        {loading && (
          <span className="sr-only" role="status">
            Loading {title}
          </span>
        )}
      </CardContent>
    </Card>
  );
}

// ── Helpers ────────────────────────────────────────────────────────

function sumBids(rows: CalibrationPoint[]): number {
  return rows.reduce((acc, r) => acc + r.bids_submitted, 0);
}

function sumWins(rows: CalibrationPoint[]): number {
  return rows.reduce((acc, r) => acc + r.wins, 0);
}

function computeWinRate(rows: CalibrationPoint[]): number | null {
  const totalBids = sumBids(rows);
  if (totalBids === 0) return null;
  return sumWins(rows) / totalBids;
}

function computeMedianPremium(rows: CalibrationPoint[]): number | null {
  const values = rows
    .map((r) => r.pct_above_low)
    .filter((v): v is number => v !== null && !Number.isNaN(v));
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[mid - 1] + sorted[mid]) / 2
    : sorted[mid];
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

function formatPercent(n: number): string {
  return `${n.toFixed(1)}%`;
}
