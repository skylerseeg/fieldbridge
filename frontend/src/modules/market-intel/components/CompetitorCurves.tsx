import { Construction } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import { useCompetitorCurves } from "../hooks/useCompetitorCurves";
import { EmptyState } from "./EmptyState";
import type { MonthsBack } from "./ModuleHeader";

/**
 * Competitor curves tab.
 *
 * Slice 1: thin shell with the four states wired (loading / error /
 * empty / populated). The Recharts ScatterChart, side Sheet
 * drilldown, and sortable table land in slice 2 — the data fetch
 * and the empty/error machinery are settled here so that change is
 * additive.
 */

const MIN_BIDS_FLOOR = 10;

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

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Competitor curves</CardTitle>
        <p className="text-xs text-muted-foreground">
          Every competitor has a pricing personality. Median rank vs.
          average premium over low, sized by bid count.
        </p>
      </CardHeader>
      <CardContent>
        {isError && (
          <EmptyState
            tone="error"
            title="Couldn't load competitor curves."
            description="Pipeline may be paused — try again or check the worker status."
            action={
              <button
                type="button"
                onClick={() => refetch()}
                className="rounded-md border border-critical/40 bg-card px-3 py-1.5 text-xs font-medium text-critical hover:bg-critical/10 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-critical"
              >
                Retry
              </button>
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
          />
        )}

        {!isError && !isLoading && data && data.length > 0 && (
          <ChartPlaceholder count={data.length} />
        )}
      </CardContent>
    </Card>
  );
}

// ── Slice-1 placeholders (replaced by Recharts + Table in slice 2) ──

function ScatterSkeleton({ "aria-label": ariaLabel }: { "aria-label": string }) {
  return (
    <div
      role="status"
      aria-busy
      aria-label={ariaLabel}
      className="space-y-3"
    >
      <div className="h-72 w-full animate-pulse rounded-md bg-muted motion-reduce:animate-none" />
      <div className="h-32 w-full animate-pulse rounded-md bg-muted/60 motion-reduce:animate-none" />
    </div>
  );
}

function ChartPlaceholder({ count }: { count: number }) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-muted/30 p-6">
      <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
        <Construction className="h-4 w-4" aria-hidden />
        Scatter + table land in slice 2
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        Data fetch is wired and returning {count.toLocaleString()} contractor
        rows. Ready to render against once the chart implementation merges.
      </p>
    </div>
  );
}
