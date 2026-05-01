import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { fetchOpportunityGaps } from "../api/client";
import { mockFetchOpportunityGaps, USE_MOCK_DATA } from "../api/mockData";
import type { OpportunityGapsParams, OpportunityRow } from "../api/types";

/**
 * Opportunity gaps — county/state cells where similar-scope work
 * happened but VanCon never bid.
 *
 * 5-minute stale time, mock toggle, namespaced query key. Same
 * conventions as the other Market Intel hooks.
 */

const FIVE_MINUTES = 5 * 60 * 1000;

export const opportunityGapsKey = {
  all: ["market-intel", "opportunity-gaps"] as const,
  list: (params: OpportunityGapsParams) =>
    [...opportunityGapsKey.all, params] as const,
};

export function useOpportunityGaps(
  params: OpportunityGapsParams,
): UseQueryResult<OpportunityRow[], Error> {
  return useQuery({
    queryKey: opportunityGapsKey.list(params),
    queryFn: () =>
      USE_MOCK_DATA
        ? mockFetchOpportunityGaps(params)
        : fetchOpportunityGaps(params),
    staleTime: FIVE_MINUTES,
  });
}
