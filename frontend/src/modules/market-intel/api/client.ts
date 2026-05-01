import { api } from "@/lib/api";

import type {
  BidCalibrationParams,
  CalibrationPoint,
  CompetitorCurveRow,
  CompetitorCurvesParams,
  OpportunityGapsParams,
  OpportunityRow,
} from "./types";

/**
 * Typed fetchers for the FastAPI `market_intel` module.
 *
 * Mounted at `/api/market-intel` (NOT `/api/v1/market-intel`) — see
 * `app/main.py`. Note the URL hyphen vs the Python package underscore.
 *
 * All three endpoints currently return `[]` while the bid-network
 * pipeline accumulates data. Hooks layer over these with the
 * VITE_USE_MOCK_DATA toggle so the UI can be exercised end-to-end
 * before real rows land.
 */

const BASE = "/api/market-intel";

// ── Fetchers ────────────────────────────────────────────────────────

export async function fetchCompetitorCurves(
  params: CompetitorCurvesParams,
): Promise<CompetitorCurveRow[]> {
  const { data } = await api.get<CompetitorCurveRow[]>(
    `${BASE}/competitor-curves`,
    {
      params: {
        states: params.states.join(","),
        months_back: params.monthsBack,
        min_bids: params.minBids,
      },
    },
  );
  return data;
}

export async function fetchOpportunityGaps(
  params: OpportunityGapsParams,
): Promise<OpportunityRow[]> {
  const { data } = await api.get<OpportunityRow[]>(
    `${BASE}/opportunity-gaps`,
    {
      params: {
        bid_min: params.bidMin,
        bid_max: params.bidMax,
        months_back: params.monthsBack,
      },
    },
  );
  return data;
}

export async function fetchBidCalibration(
  params: BidCalibrationParams,
): Promise<CalibrationPoint[]> {
  const { data } = await api.get<CalibrationPoint[]>(
    `${BASE}/bid-calibration`,
    {
      params: {
        contractor_name_match: params.contractorNameMatch,
      },
    },
  );
  return data;
}
