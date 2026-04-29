import { lazy, Suspense, useState } from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { KpiStrip } from "./components/KpiStrip";
import {
  ModuleHeader,
  STATE_OPTIONS,
  type MonthsBack,
} from "./components/ModuleHeader";

/**
 * Market Intel — page entry.
 *
 * Layout matches the Cost Coding / Equipment page weight:
 *
 *   ┌── Header ──────────────────────────────────────────┐
 *   │ H1 + subtitle              · State + months filter │
 *   ├── KPI strip (4 tiles) ─────────────────────────────┤
 *   ├── Tabs ────────────────────────────────────────────┤
 *   │   Competitor curves · Opportunity gaps · Bid       │
 *   │   calibration  (each lazy-loaded)                  │
 *   └────────────────────────────────────────────────────┘
 *
 * Filter state lives here so all three tabs share the same window.
 * Each tab is a React.lazy import wrapped in Suspense so the
 * three Recharts payloads are split across chunks (per the brief
 * acceptance criteria).
 *
 * Routes.tsx imports `MarketIntelPage` as a *named* export — that
 * stays. The default export below is for symmetry with the brief's
 * "default export — route entry" line and future-proofs the lazy
 * import path if we ever flip the route table to lazy-route mode.
 */

const CompetitorCurves = lazy(() => import("./components/CompetitorCurves"));
const OpportunityGaps = lazy(() => import("./components/OpportunityGaps"));
const BidCalibration = lazy(() => import("./components/BidCalibration"));

const DEFAULT_STATES: string[] = [...STATE_OPTIONS];
const DEFAULT_MONTHS_BACK: MonthsBack = 36;

export function MarketIntelPage() {
  const [states, setStates] = useState<string[]>(DEFAULT_STATES);
  const [monthsBack, setMonthsBack] = useState<MonthsBack>(DEFAULT_MONTHS_BACK);

  return (
    <div className="space-y-6 p-6 lg:p-8">
      <ModuleHeader
        states={states}
        onStatesChange={setStates}
        monthsBack={monthsBack}
        onMonthsBackChange={setMonthsBack}
      />

      <KpiStrip states={states} monthsBack={monthsBack} />

      <Tabs defaultValue="curves" className="w-full">
        <TabsList>
          <TabsTrigger value="curves">Competitor curves</TabsTrigger>
          <TabsTrigger value="gaps">Opportunity gaps</TabsTrigger>
          <TabsTrigger value="calibration">Bid calibration</TabsTrigger>
        </TabsList>

        <div className="mt-4">
          <TabsContent value="curves" className="mt-0">
            <Suspense fallback={<TabFallback label="Competitor curves" />}>
              <CompetitorCurves states={states} monthsBack={monthsBack} />
            </Suspense>
          </TabsContent>
          <TabsContent value="gaps" className="mt-0">
            <Suspense fallback={<TabFallback label="Opportunity gaps" />}>
              <OpportunityGaps monthsBack={monthsBack} />
            </Suspense>
          </TabsContent>
          <TabsContent value="calibration" className="mt-0">
            <Suspense fallback={<TabFallback label="Bid calibration" />}>
              <BidCalibration />
            </Suspense>
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}

export default MarketIntelPage;

function TabFallback({ label }: { label: string }) {
  return (
    <div
      role="status"
      aria-busy
      aria-label={`Loading ${label}`}
      className="space-y-3"
    >
      <div className="h-10 w-1/3 animate-pulse rounded-md bg-muted motion-reduce:animate-none" />
      <div className="h-72 w-full animate-pulse rounded-md bg-muted motion-reduce:animate-none" />
    </div>
  );
}
