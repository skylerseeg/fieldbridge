import { useMemo } from "react";
import { ArrowLeft, ExternalLink, MapPin } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import { EmptyState } from "./components/EmptyState";
import { useCountyGapDetail } from "./hooks/useCountyGapDetail";
import type { CountyGapEvent } from "./api/types";

/**
 * Gap detail page — drill-in from the Opportunity gaps top-N list.
 *
 * Reached from `/market-intel/gap/:state/:county` (React Router URL-
 * decodes the `:county` param automatically). Fetches per-event
 * detail via `useCountyGapDetail` against
 * `GET /api/market-intel/gap/{state}/{county}` (or its mock equivalent
 * when `VITE_USE_MOCK_DATA=true`).
 *
 * Renders:
 *   - Back link to the parent surface
 *   - Header: county + state with MapPin icon
 *   - Summary line: event count + total low-bid value
 *   - Table: one row per bid event (date, title, owner, winner,
 *     low bid, scope codes, source link)
 *
 * State coverage:
 *   - Loading        → skeleton table
 *   - Error          → EmptyState with retry
 *   - Empty data     → EmptyState (caller never bid here OR no events
 *                      in the active window)
 *   - Bad URL params → "Missing parameters" EmptyState
 */

// Default filter window — matches the Opportunity gaps tab so the
// drill-in shows roughly the events that contributed to the
// `missed_count` aggregate the user just clicked through.
const DEFAULT_BID_MIN = 250_000;
const DEFAULT_BID_MAX = 5_000_000;
const DEFAULT_MONTHS_BACK = 24;

function formatMoney(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (abs >= 10_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toLocaleString()}`;
}

function formatDate(iso: string): string {
  // Backend ships ISO date strings (YYYY-MM-DD). Format as a short
  // human label without dragging a date-fns dep in for one call site.
  const [year, month, day] = iso.split("-").map(Number);
  if (!year || !month || !day) return iso;
  const d = new Date(Date.UTC(year, month - 1, day));
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

export function GapDetailPage() {
  const { state = "", county = "" } = useParams<{
    state: string;
    county: string;
  }>();

  const stateCode = state.toUpperCase();
  const label = county ? `${county}, ${stateCode}` : stateCode;
  const hasParams = Boolean(stateCode && county);

  const { data, isLoading, isError, refetch } = useCountyGapDetail({
    state: stateCode,
    county,
    bidMin: DEFAULT_BID_MIN,
    bidMax: DEFAULT_BID_MAX,
    monthsBack: DEFAULT_MONTHS_BACK,
  });

  const totalValue = useMemo(
    () => (data ?? []).reduce((sum, row) => sum + row.low_bid_amount, 0),
    [data],
  );

  return (
    <div className="space-y-6 p-6 lg:p-8">
      <Link
        to="/market-intel"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
        Back to Bid Intelligence
      </Link>

      <header className="space-y-1">
        <h1 className="flex items-center gap-2 text-[28px] font-medium tracking-tight text-foreground">
          <MapPin className="h-6 w-6 text-muted-foreground" aria-hidden />
          {label || "Opportunity gap"}
        </h1>
        <p className="text-sm text-muted-foreground">
          Public bid awards in this county where VanCon never appeared on the
          bidder list.
        </p>
      </header>

      {!hasParams && (
        <EmptyState
          tone="default"
          title="Missing parameters"
          description="The URL needs both a state code and a county. Return to the Opportunity gaps tab and click a row."
          data-testid="gap-detail-missing-params"
          action={
            <Button asChild variant="outline" size="sm">
              <Link to="/market-intel">Back to Bid Intelligence</Link>
            </Button>
          }
        />
      )}

      {hasParams && (
        <Card>
          <CardHeader className="flex flex-col gap-1 space-y-0 sm:flex-row sm:items-center sm:justify-between">
            <div className="space-y-0.5">
              <CardTitle className="text-base">Bid events</CardTitle>
              <p className="text-xs text-muted-foreground">
                Window: last {DEFAULT_MONTHS_BACK} months · Bid range{" "}
                {formatMoney(DEFAULT_BID_MIN)}–{formatMoney(DEFAULT_BID_MAX)}
              </p>
            </div>
            {!isError && !isLoading && data && data.length > 0 && (
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <span>
                  <span className="font-mono tabular-nums text-foreground">
                    {data.length}
                  </span>{" "}
                  event{data.length === 1 ? "" : "s"}
                </span>
                <span aria-hidden>·</span>
                <span>
                  <span className="font-mono tabular-nums text-foreground">
                    {formatMoney(totalValue)}
                  </span>{" "}
                  total low bid
                </span>
              </div>
            )}
          </CardHeader>

          <CardContent>
            {isError && (
              <EmptyState
                tone="error"
                title="Couldn't load gap detail."
                description="The bid-network pipeline may be paused, or the backend is unreachable. Try again."
                data-testid="gap-detail-error"
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
              <TableSkeleton aria-label={`Loading bid events for ${label}`} />
            )}

            {!isError && !isLoading && data && data.length === 0 && (
              <EmptyState
                tone="info"
                title="No bid events to show."
                description="Either VanCon was on every bidder list in this county within the active window, or the bid-network pipeline hasn't accumulated rows here yet."
                data-testid="gap-detail-empty"
                action={
                  <Button asChild variant="outline" size="sm">
                    <Link to="/market-intel">Back to Bid Intelligence</Link>
                  </Button>
                }
              />
            )}

            {!isError && !isLoading && data && data.length > 0 && (
              <BidEventTable rows={data} />
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default GapDetailPage;

// ── Table ───────────────────────────────────────────────────────────

function BidEventTable({ rows }: { rows: CountyGapEvent[] }) {
  return (
    <div
      className="overflow-x-auto"
      role="region"
      aria-label="Bid events that were awarded without a VanCon bid"
    >
      <table className="w-full min-w-[820px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-muted-foreground">
            <th scope="col" className="px-3 py-2 font-medium">
              Bid open
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Project
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Owner
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Winning bidder
            </th>
            <th
              scope="col"
              className="px-3 py-2 text-right font-medium tabular-nums"
            >
              Low bid
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Scope
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Source
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((row) => (
            <tr
              key={row.bid_event_id}
              className="align-top hover:bg-muted/40"
            >
              <td className="whitespace-nowrap px-3 py-3 font-mono text-xs tabular-nums text-muted-foreground">
                {formatDate(row.bid_open_date)}
              </td>
              <td className="px-3 py-3">
                <div className="font-medium text-foreground">
                  {row.project_title}
                </div>
                {row.solicitation_id && (
                  <div className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                    {row.solicitation_id}
                  </div>
                )}
              </td>
              <td className="px-3 py-3 text-muted-foreground">
                {row.project_owner ?? "—"}
              </td>
              <td className="px-3 py-3 text-foreground">
                {row.low_bidder_name}
              </td>
              <td className="whitespace-nowrap px-3 py-3 text-right font-mono tabular-nums text-foreground">
                {formatMoney(row.low_bid_amount)}
              </td>
              <td className="px-3 py-3">
                {row.csi_codes.length === 0 ? (
                  <span className="text-muted-foreground">—</span>
                ) : (
                  <div className="flex flex-wrap gap-1">
                    {row.csi_codes.slice(0, 3).map((code) => (
                      <Badge
                        key={code}
                        variant="mono"
                        className="text-[10px]"
                      >
                        {code}
                      </Badge>
                    ))}
                    {row.csi_codes.length > 3 && (
                      <span className="text-[10px] text-muted-foreground">
                        +{row.csi_codes.length - 3}
                      </span>
                    )}
                  </div>
                )}
              </td>
              <td className="px-3 py-3">
                <a
                  href={row.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-info hover:underline"
                  aria-label={`Open source bid abstract for ${row.project_title} in a new tab`}
                >
                  <ExternalLink className="h-3 w-3" aria-hidden />
                  View
                </a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Skeleton ────────────────────────────────────────────────────────

function TableSkeleton({ "aria-label": ariaLabel }: { "aria-label": string }) {
  return (
    <div
      role="status"
      aria-busy
      aria-label={ariaLabel}
      data-testid="gap-detail-loading"
      className="space-y-2"
    >
      <div className="h-8 w-full animate-pulse rounded-md bg-muted motion-reduce:animate-none" />
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="h-12 w-full animate-pulse rounded-md bg-muted/60 motion-reduce:animate-none"
        />
      ))}
    </div>
  );
}
