/**
 * Market Intel — placeholder shell.
 *
 * Lead-scaffolded for `feature/market-intel-v15`. The Market Intel
 * Frontend Worker replaces this file with the full page per the brief
 * at `frontend/src/modules/market-intel/PROPOSED_CHANGES.md`.
 *
 * Until then this exists so `routes.tsx` resolves, `/market-intel`
 * doesn't 404, and the nav entry under Intelligence has a target.
 */
export function MarketIntelPage() {
  return (
    <div className="space-y-2 p-6">
      <h1 className="text-2xl font-medium tracking-tight text-foreground">
        Bid intelligence
      </h1>
      <p className="text-sm text-muted-foreground">
        Public bid intelligence across the western network. Pricing curves,
        missed opportunities, and self-calibration against the low bid.
      </p>
      <div
        className="mt-6 rounded-lg border border-dashed border-border bg-muted/40 p-8 text-sm text-muted-foreground"
        role="status"
      >
        Module is scaffolded. The full UI lands when the Market Intel Frontend
        Worker completes the brief at
        {" "}
        <code className="rounded bg-muted px-1 font-mono text-xs">
          frontend/src/modules/market-intel/PROPOSED_CHANGES.md
        </code>
        . Backend endpoints are live and currently return empty arrays until
        the bid-network pipeline accumulates data.
      </div>
    </div>
  );
}
