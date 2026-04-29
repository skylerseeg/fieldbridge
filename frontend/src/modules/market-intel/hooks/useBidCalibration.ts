import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { fetchBidCalibration } from "../api/client";
import { mockFetchBidCalibration, USE_MOCK_DATA } from "../api/mockData";
import type { BidCalibrationParams, CalibrationPoint } from "../api/types";

/**
 * Bid calibration — quarterly self-comparison vs. the low bid.
 *
 * 5-minute stale time, mock toggle, namespaced query key. Defaults
 * to matching "van con" since this branch is built for VanCon's
 * own seat; multi-tenant overlays are v3.
 */

const FIVE_MINUTES = 5 * 60 * 1000;

export const bidCalibrationKey = {
  all: ["market-intel", "bid-calibration"] as const,
  list: (params: BidCalibrationParams) =>
    [...bidCalibrationKey.all, params] as const,
};

export function useBidCalibration(
  params: BidCalibrationParams,
): UseQueryResult<CalibrationPoint[], Error> {
  return useQuery({
    queryKey: bidCalibrationKey.list(params),
    queryFn: () =>
      USE_MOCK_DATA
        ? mockFetchBidCalibration(params)
        : fetchBidCalibration(params),
    staleTime: FIVE_MINUTES,
  });
}
