import { Construction } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import { useOpportunityGaps } from "../hooks/useOpportunityGaps";
import { EmptyState } from "./EmptyState";
import type { MonthsBack } from "./ModuleHeader";

/**
 * Opportunity gaps tab.
 *
 * Slice 1: state/error/empty/loading wiring against the same fetch
 * shape the brief specifies. The grouped BarChart + top-10 list
 * land in slice 3.
 *
 * Default bid-window 250k–5M comes from the brief; once a sensible
 * range filter is added to the page header we'll lift this up.
 */

const DEFAULT_BID_MIN = 250_000;
const DEFAULT_BID_MAX = 5_000_000;

export interface OpportunityGapsProps {
  monthsBack: MonthsBack;
}

export default function OpportunityGaps({ monthsBack }: OpportunityGapsProps) {
  const { data, isLoading, isError, refetch } = useOpportunityGaps({
    bidMin: DEFAULT_BID_MIN,
    bidMax: DEFAULT_BID_MAX,
    monthsBack,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Opportunity gaps</CardTitle>
        <p className="text-xs text-muted-foreground">
          Counties where similar-scope work happened but VanCon never bid.
          Top-10 gaps surface the densest opportunities first.
        </p>
      </CardHeader>
      <CardContent>
        {isError && (
          <EmptyState
            tone="error"
            title="Couldn't load opportunity gaps."
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
          <BarSkeleton aria-label="Loading opportunity gaps" />
        )}

        {!isError && !isLoading && data && data.length === 0 && (
          <EmptyState
            tone="info"
            title="No gaps to surface yet."
            description="Either the bid-network ingest hasn't accumulated enough rows for the selected window, or your filters are too tight."
          />
        )}

        {!isError && !isLoading && data && data.length > 0 && (
          <ChartPlaceholder count={data.length} />
        )}
      </CardContent>
    </Card>
  );
}

function BarSkeleton({ "aria-label": ariaLabel }: { "aria-label": string }) {
  return (
    <div
      role="status"
      aria-busy
      aria-label={ariaLabel}
      className="grid grid-cols-1 gap-3 lg:grid-cols-3"
    >
      <div className="h-72 w-full animate-pulse rounded-md bg-muted motion-reduce:animate-none lg:col-span-2" />
      <div className="h-72 w-full animate-pulse rounded-md bg-muted/60 motion-reduce:animate-none" />
    </div>
  );
}

function ChartPlaceholder({ count }: { count: number }) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-muted/30 p-6">
      <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
        <Construction className="h-4 w-4" aria-hidden />
        Bars + top-10 list land in slice 3
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        Data fetch is wired and returning {count.toLocaleString()} county-level
        gap rows. Chart and ranked list ready to layer on next.
      </p>
    </div>
  );
}
