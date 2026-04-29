import { Construction } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import { useBidCalibration } from "../hooks/useBidCalibration";
import { EmptyState } from "./EmptyState";

/**
 * Bid calibration tab.
 *
 * Slice 1: empty / loading / error / populated states wired against
 * the calibration query. The dual-axis ComposedChart + quarterly
 * table land in slice 4.
 *
 * Hard-coded to "van con" for v1.5/v2 — multi-tenant overlays are
 * v3 (see docs/market-intel.md).
 */

const VANCON_NAME_MATCH = "van con";

export default function BidCalibration() {
  const { data, isLoading, isError, refetch } = useBidCalibration({
    contractorNameMatch: VANCON_NAME_MATCH,
  });

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
      <CardContent>
        {isError && (
          <EmptyState
            tone="error"
            title="Couldn't load bid calibration."
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
          <ComposedSkeleton aria-label="Loading bid calibration" />
        )}

        {!isError && !isLoading && data && data.length === 0 && (
          <EmptyState
            tone="info"
            title="No calibration data yet."
            description="Calibration appears once VanCon's bid history syncs and at least one quarter of public bid results lands in the window."
          />
        )}

        {!isError && !isLoading && data && data.length > 0 && (
          <ChartPlaceholder count={data.length} />
        )}
      </CardContent>
    </Card>
  );
}

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
        Composed chart + quarter table land in slice 4
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        Data fetch is wired and returning {count.toLocaleString()} quarters of
        calibration data. Dual-axis chart and highlighted-row table ready to
        render against.
      </p>
    </div>
  );
}
