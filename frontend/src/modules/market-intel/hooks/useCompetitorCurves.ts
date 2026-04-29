import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { fetchCompetitorCurves } from "../api/client";
import { mockFetchCompetitorCurves, USE_MOCK_DATA } from "../api/mockData";
import type { CompetitorCurveRow, CompetitorCurvesParams } from "../api/types";

/**
 * Competitor pricing curves — one row per contractor, network-wide.
 *
 * Brief contract:
 *   - 5-minute stale time. Public bid data refreshes nightly via the
 *     n8n cron, so re-fetching on every focus/mount is wasteful.
 *   - Honors VITE_USE_MOCK_DATA so the UI works before the pipeline
 *     accumulates real rows. The dead branch is tree-shaken in prod.
 *   - Query key is namespaced under `market-intel.competitor-curves`
 *     and includes the params so the cache slices per-filter combo.
 */

const FIVE_MINUTES = 5 * 60 * 1000;

export const competitorCurvesKey = {
  all: ["market-intel", "competitor-curves"] as const,
  list: (params: CompetitorCurvesParams) =>
    [...competitorCurvesKey.all, params] as const,
};

export function useCompetitorCurves(
  params: CompetitorCurvesParams,
): UseQueryResult<CompetitorCurveRow[], Error> {
  return useQuery({
    queryKey: competitorCurvesKey.list(params),
    queryFn: () =>
      USE_MOCK_DATA
        ? mockFetchCompetitorCurves(params)
        : fetchCompetitorCurves(params),
    staleTime: FIVE_MINUTES,
  });
}
