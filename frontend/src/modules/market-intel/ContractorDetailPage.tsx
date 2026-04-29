import { ArrowLeft, Construction } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Contractor detail — placeholder page.
 *
 * Reached from the Competitor curves drilldown's "View bid history"
 * button via `navigate("/market-intel/contractor/${slug}")`. Slug is
 * a kebab-cased version of `contractor_name` (see
 * `slugifyContractor` in `components/CompetitorCurves.tsx`).
 *
 * v1.5 scope: this page renders a "coming soon" placeholder with
 * the slug echoed back, plus a Back link to the main module page.
 * The full bid-history view is v2.1+ and depends on a
 * `/api/market-intel/contractor/{slug}` endpoint that doesn't yet
 * exist on the backend.
 *
 * Route wiring is Lead-owned (`frontend/src/routes.tsx`); the wire
 * snippet lives in `PROPOSED_CHANGES_routes.md` next to this file.
 */

export function ContractorDetailPage() {
  const { slug = "" } = useParams<{ slug: string }>();

  // Best-effort de-slugification for display only — turns
  // "ralph-l-wadsworth-construction" into "Ralph L Wadsworth Construction".
  const display = slug
    .split("-")
    .filter(Boolean)
    .map((word) => word[0]?.toUpperCase() + word.slice(1))
    .join(" ");

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
        <h1 className="text-[28px] font-medium tracking-tight text-foreground">
          {display || "Contractor"}
        </h1>
        <p className="text-sm text-muted-foreground">
          Contractor bid history across the western network.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Construction className="h-4 w-4 text-info" aria-hidden />
            Bid history not implemented yet
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>
            The detail view lands in a follow-up slice (v2.1+). It depends on
            a backend <code className="rounded bg-muted px-1 font-mono text-xs">
              /api/market-intel/contractor/{"{"}slug{"}"}
            </code>{" "}
            endpoint that doesn't yet exist.
          </p>
          <p>
            Until then, the network-wide pricing profile is visible on the
            <Link
              to="/market-intel"
              className="ml-1 inline-flex items-center gap-1 text-info hover:underline"
            >
              Competitor curves
            </Link>{" "}
            tab — click any row to see the same headline numbers.
          </p>
          <p className="font-mono text-xs">
            Slug:{" "}
            <span className="rounded bg-muted px-1 py-0.5">
              {slug || "(empty)"}
            </span>
          </p>
          <Button asChild variant="outline" size="sm">
            <Link to="/market-intel">Back to Bid intelligence</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

export default ContractorDetailPage;
