import { ArrowLeft, Construction, MapPin } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Gap detail — placeholder page.
 *
 * Reached from the Opportunity gaps top-10 list via
 * `navigate("/market-intel/gap/${row.state}/${encodeURIComponent(row.county)}")`.
 * React Router URL-decodes the `:county` param automatically.
 *
 * v1.5 scope: this page renders a "coming soon" placeholder echoing
 * the state + county pair, plus a Back link. The full per-county bid
 * list (state DOT awards + NAPC posts intersected with VanCon's
 * historical scopes) is v2.1+ and depends on a
 * `/api/market-intel/gap/{state}/{county}` endpoint not yet on the
 * backend.
 *
 * Route wiring is Lead-owned (`frontend/src/routes.tsx`); the wire
 * snippet lives in `PROPOSED_CHANGES_routes.md` next to this file.
 */

export function GapDetailPage() {
  const { state = "", county = "" } = useParams<{
    state: string;
    county: string;
  }>();

  const stateLabel = state.toUpperCase();
  const label = county ? `${county}, ${stateLabel}` : stateLabel;

  return (
    <div className="space-y-6 p-6 lg:p-8">
      <Link
        to="/market-intel"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
        Back to Bid intelligence
      </Link>

      <header className="space-y-1">
        <h1 className="flex items-center gap-2 text-[28px] font-medium tracking-tight text-foreground">
          <MapPin className="h-6 w-6 text-muted-foreground" aria-hidden />
          {label || "Opportunity gap"}
        </h1>
        <p className="text-sm text-muted-foreground">
          Public bid awards in this county that VanCon never bid on.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Construction className="h-4 w-4 text-info" aria-hidden />
            Per-county detail not implemented yet
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>
            The detail view lands in a follow-up slice (v2.1+). It depends on
            a backend{" "}
            <code className="rounded bg-muted px-1 font-mono text-xs">
              /api/market-intel/gap/{"{"}state{"}"}/{"{"}county{"}"}
            </code>{" "}
            endpoint that doesn't yet exist, and on the state DOT bid-tab
            scrapers (now the primary ingest path per the
            2026-04-29 strategic pivot in <code>docs/market-intel.md</code>).
          </p>
          <p>
            Until then, county-level miss counts and scope codes are visible
            in the
            <Link
              to="/market-intel"
              className="ml-1 inline-flex items-center gap-1 text-info hover:underline"
            >
              Opportunity gaps
            </Link>{" "}
            tab.
          </p>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Badge variant="mono">{stateLabel || "—"}</Badge>
            <span className="font-mono text-xs">
              county: {county || "(empty)"}
            </span>
          </div>
          <Button asChild variant="outline" size="sm">
            <Link to="/market-intel">Back to Bid intelligence</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

export default GapDetailPage;
