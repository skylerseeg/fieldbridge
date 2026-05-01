import { AgentAlertsCard } from "@/components/dashboard/AgentAlertsCard";
import { FleetInsightsCard } from "@/components/dashboard/FleetInsightsCard";
import { PerformanceCard } from "@/components/dashboard/PerformanceCard";

/**
 * Home dashboard. Three cards:
 *   1. Performance (stacked metric strip + bar chart)
 *   2. Fleet Insights (7-tile grid)
 *   3. Agent Alerts (donut + feed)
 *
 * Data is still hardcoded inside each card's local data module. Commit 3+
 * replace those with /api/v1/dashboard/* queries via useQuery().
 */
export function HomePage() {
  return (
    <div className="flex flex-col gap-5">
      <PerformanceCard />
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_1.2fr]">
        <FleetInsightsCard />
        <AgentAlertsCard />
      </div>
    </div>
  );
}
