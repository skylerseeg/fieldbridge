import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { fetchCountyGapDetail } from "../api/client";
import { mockFetchCountyGapDetail, USE_MOCK_DATA } from "../api/mockData";
import type { CountyGapDetailParams, CountyGapEvent } from "../api/types";

/**
 * Per-event drill-in for one (state, county) cell of the
 * Opportunity gaps surface.
 *
 * 5-minute stale time, mock toggle, namespaced query key. Same
 * conventions as `useOpportunityGaps`. Disabled while either
 * `state` or `county` is empty so the route can render its
 * "missing param" empty state without a wasted fetch.
 */

const FIVE_MINUTES = 5 * 60 * 1000;

export const countyGapDetailKey = {
  all: ["market-intel", "county-gap-detail"] as const,
  list: (params: CountyGapDetailParams) =>
    [...countyGapDetailKey.all, params] as const,
};

export function useCountyGapDetail(
  params: CountyGapDetailParams,
): UseQueryResult<CountyGapEvent[], Error> {
  return useQuery({
    queryKey: countyGapDetailKey.list(params),
    queryFn: () =>
      USE_MOCK_DATA
        ? mockFetchCountyGapDetail(params)
        : fetchCountyGapDetail(params),
    staleTime: FIVE_MINUTES,
    enabled: Boolean(params.state && params.county),
  });
}
