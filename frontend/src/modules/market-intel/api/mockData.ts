import type {
  BidCalibrationParams,
  CalibrationPoint,
  CompetitorCurveRow,
  CompetitorCurvesParams,
  OpportunityGapsParams,
  OpportunityRow,
} from "./types";

/**
 * Realistic fixtures for offline UI development.
 *
 * Active when `VITE_USE_MOCK_DATA === "true"`. The hooks layer chooses
 * between this module and the live `client.ts` fetchers based on that
 * env flag — so the UI is fully exercisable before the bid-network
 * pipeline accumulates real rows.
 *
 * Numbers are hand-tuned to land in the ranges the brief specifies:
 *
 *   - 18 competitors, bid_count 12–180, median_rank 1.4–4.8,
 *     premium 0.5%–18%, win_rate 0.05–0.42.
 *   - 30 opportunity-gap rows across UT/ID/NV/WY/CO/AZ.
 *   - 8 quarters of calibration: 12–28 bids, 1–9 wins,
 *     pct_above_low between 0.8% and 11%.
 *
 * The fetcher signatures match the live client exactly so swapping
 * back to real data is a one-line change in each hook.
 */

// ── Competitors ─────────────────────────────────────────────────────
//
// Names are real regional players from the western heavy-civil
// market. Numbers are illustrative; nothing here is sourced from an
// actual bid tabulation.

const COMPETITORS: CompetitorCurveRow[] = [
  {
    contractor_name: "Sunroc Corporation",
    bid_count: 142,
    avg_premium_over_low: 0.038,
    median_rank: 1.7,
    win_rate: 0.36,
  },
  {
    contractor_name: "Geneva Rock Products",
    bid_count: 168,
    avg_premium_over_low: 0.045,
    median_rank: 1.9,
    win_rate: 0.32,
  },
  {
    contractor_name: "Granite Construction",
    bid_count: 124,
    avg_premium_over_low: 0.061,
    median_rank: 2.4,
    win_rate: 0.21,
  },
  {
    contractor_name: "Staker Parson Companies",
    bid_count: 156,
    avg_premium_over_low: 0.041,
    median_rank: 1.8,
    win_rate: 0.34,
  },
  {
    contractor_name: "Whitaker Construction",
    bid_count: 78,
    avg_premium_over_low: 0.058,
    median_rank: 2.6,
    win_rate: 0.18,
  },
  {
    contractor_name: "Kilgore Companies",
    bid_count: 134,
    avg_premium_over_low: 0.052,
    median_rank: 2.2,
    win_rate: 0.24,
  },
  {
    contractor_name: "Wadsworth Brothers",
    bid_count: 96,
    avg_premium_over_low: 0.071,
    median_rank: 2.9,
    win_rate: 0.15,
  },
  {
    contractor_name: "HK Contractors",
    bid_count: 64,
    avg_premium_over_low: 0.082,
    median_rank: 3.1,
    win_rate: 0.13,
  },
  {
    contractor_name: "Depatco",
    bid_count: 52,
    avg_premium_over_low: 0.094,
    median_rank: 3.4,
    win_rate: 0.11,
  },
  {
    contractor_name: "Galicia's Concrete",
    bid_count: 28,
    avg_premium_over_low: 0.118,
    median_rank: 3.8,
    win_rate: 0.08,
  },
  {
    contractor_name: "B Squared Legacy GC",
    bid_count: 38,
    avg_premium_over_low: 0.106,
    median_rank: 3.6,
    win_rate: 0.09,
  },
  {
    contractor_name: "Wheeler Machinery",
    bid_count: 22,
    avg_premium_over_low: 0.143,
    median_rank: 4.2,
    win_rate: 0.06,
  },
  {
    contractor_name: "Mountain Region Constructors",
    bid_count: 88,
    avg_premium_over_low: 0.066,
    median_rank: 2.7,
    win_rate: 0.17,
  },
  {
    contractor_name: "Ames Construction",
    bid_count: 72,
    avg_premium_over_low: 0.054,
    median_rank: 2.3,
    win_rate: 0.22,
  },
  {
    contractor_name: "W. W. Clyde & Co.",
    bid_count: 110,
    avg_premium_over_low: 0.047,
    median_rank: 2.0,
    win_rate: 0.28,
  },
  {
    contractor_name: "Ralph L. Wadsworth Construction",
    bid_count: 84,
    avg_premium_over_low: 0.063,
    median_rank: 2.5,
    win_rate: 0.20,
  },
  {
    contractor_name: "Q&D Construction",
    bid_count: 42,
    avg_premium_over_low: 0.089,
    median_rank: 3.2,
    win_rate: 0.12,
  },
  {
    contractor_name: "Burdick Materials",
    bid_count: 18,
    avg_premium_over_low: 0.176,
    median_rank: 4.8,
    win_rate: 0.05,
  },
];

// ── Opportunity gaps ────────────────────────────────────────────────
//
// 30 county/state cells where similar-scope work happened but VanCon
// never bid. CSI-code shorthand is illustrative.

const OPPORTUNITY_GAPS: OpportunityRow[] = [
  // Utah
  { state: "UT", county: "Salt Lake", missed_count: 18, avg_low_bid: 1_240_000, top_scope_codes: ["32 11 23", "31 23 16"] },
  { state: "UT", county: "Utah", missed_count: 14, avg_low_bid: 980_000, top_scope_codes: ["32 12 16", "31 23 33"] },
  { state: "UT", county: "Davis", missed_count: 11, avg_low_bid: 1_540_000, top_scope_codes: ["32 11 23", "33 41 00"] },
  { state: "UT", county: "Weber", missed_count: 9, avg_low_bid: 720_000, top_scope_codes: ["32 12 16"] },
  { state: "UT", county: "Washington", missed_count: 7, avg_low_bid: 2_180_000, top_scope_codes: ["31 23 16", "33 11 00"] },
  { state: "UT", county: "Cache", missed_count: 6, avg_low_bid: 640_000, top_scope_codes: ["32 11 23"] },
  // Idaho
  { state: "ID", county: "Ada", missed_count: 24, avg_low_bid: 1_820_000, top_scope_codes: ["32 11 23", "31 23 16"] },
  { state: "ID", county: "Canyon", missed_count: 16, avg_low_bid: 940_000, top_scope_codes: ["32 12 16"] },
  { state: "ID", county: "Bonneville", missed_count: 12, avg_low_bid: 1_120_000, top_scope_codes: ["33 41 00", "32 11 23"] },
  { state: "ID", county: "Bannock", missed_count: 8, avg_low_bid: 680_000, top_scope_codes: ["31 23 33"] },
  { state: "ID", county: "Twin Falls", missed_count: 10, avg_low_bid: 1_360_000, top_scope_codes: ["32 11 23", "33 11 00"] },
  { state: "ID", county: "Kootenai", missed_count: 5, avg_low_bid: 2_240_000, top_scope_codes: ["31 23 16"] },
  // Nevada
  { state: "NV", county: "Clark", missed_count: 22, avg_low_bid: 3_120_000, top_scope_codes: ["32 11 23", "33 41 00"] },
  { state: "NV", county: "Washoe", missed_count: 13, avg_low_bid: 1_460_000, top_scope_codes: ["32 12 16", "31 23 16"] },
  { state: "NV", county: "Elko", missed_count: 4, avg_low_bid: 880_000, top_scope_codes: ["31 23 33"] },
  { state: "NV", county: "Lyon", missed_count: 3, avg_low_bid: 540_000, top_scope_codes: ["32 11 23"] },
  // Wyoming
  { state: "WY", county: "Laramie", missed_count: 8, avg_low_bid: 1_080_000, top_scope_codes: ["32 11 23", "33 11 00"] },
  { state: "WY", county: "Natrona", missed_count: 6, avg_low_bid: 760_000, top_scope_codes: ["31 23 16"] },
  { state: "WY", county: "Sweetwater", missed_count: 5, avg_low_bid: 1_320_000, top_scope_codes: ["32 12 16"] },
  { state: "WY", county: "Teton", missed_count: 3, avg_low_bid: 1_980_000, top_scope_codes: ["32 11 23"] },
  // Colorado
  { state: "CO", county: "Denver", missed_count: 19, avg_low_bid: 2_460_000, top_scope_codes: ["32 11 23", "33 41 00"] },
  { state: "CO", county: "El Paso", missed_count: 12, avg_low_bid: 1_180_000, top_scope_codes: ["32 12 16"] },
  { state: "CO", county: "Larimer", missed_count: 9, avg_low_bid: 840_000, top_scope_codes: ["31 23 16"] },
  { state: "CO", county: "Weld", missed_count: 11, avg_low_bid: 1_640_000, top_scope_codes: ["33 11 00", "32 11 23"] },
  { state: "CO", county: "Mesa", missed_count: 6, avg_low_bid: 720_000, top_scope_codes: ["32 12 16"] },
  // Arizona
  { state: "AZ", county: "Maricopa", missed_count: 21, avg_low_bid: 2_980_000, top_scope_codes: ["32 11 23", "31 23 16"] },
  { state: "AZ", county: "Pima", missed_count: 14, avg_low_bid: 1_540_000, top_scope_codes: ["32 12 16"] },
  { state: "AZ", county: "Pinal", missed_count: 7, avg_low_bid: 920_000, top_scope_codes: ["33 41 00"] },
  { state: "AZ", county: "Coconino", missed_count: 5, avg_low_bid: 1_240_000, top_scope_codes: ["32 11 23"] },
  { state: "AZ", county: "Yavapai", missed_count: 4, avg_low_bid: 680_000, top_scope_codes: ["31 23 33"] },
];

// ── Bid calibration (VanCon, last 8 quarters) ───────────────────────

const CALIBRATION: CalibrationPoint[] = [
  { quarter: "2024-04-01", bids_submitted: 14, wins: 2, avg_rank: 3.2, pct_above_low: 0.094 },
  { quarter: "2024-07-01", bids_submitted: 16, wins: 3, avg_rank: 2.9, pct_above_low: 0.108 },
  { quarter: "2024-10-01", bids_submitted: 22, wins: 5, avg_rank: 2.4, pct_above_low: 0.078 },
  { quarter: "2025-01-01", bids_submitted: 19, wins: 4, avg_rank: 2.6, pct_above_low: 0.083 },
  { quarter: "2025-04-01", bids_submitted: 24, wins: 6, avg_rank: 2.2, pct_above_low: 0.061 },
  { quarter: "2025-07-01", bids_submitted: 21, wins: 7, avg_rank: 2.0, pct_above_low: 0.044 },
  { quarter: "2025-10-01", bids_submitted: 26, wins: 8, avg_rank: 1.8, pct_above_low: 0.029 },
  { quarter: "2026-01-01", bids_submitted: 28, wins: 9, avg_rank: 1.7, pct_above_low: 0.018 },
];

// ── Mock fetchers ───────────────────────────────────────────────────
//
// Honor the param shapes so swapping mock ↔ live is a no-op for the
// hook signature. We do *some* light filtering so filters in the UI
// have visible effect even on mock data.

function simulateLatencyMs(): number {
  // Tight band: enough to flash skeletons in dev, not enough to be
  // annoying. Tests stub this away by mocking the hook layer.
  return 120 + Math.floor(Math.random() * 180);
}

function delay<T>(value: T): Promise<T> {
  return new Promise((resolve) => {
    setTimeout(() => resolve(value), simulateLatencyMs());
  });
}

export async function mockFetchCompetitorCurves(
  params: CompetitorCurvesParams,
): Promise<CompetitorCurveRow[]> {
  // States and months_back don't materially shape the mock universe —
  // the dataset is a single network-wide snapshot — so we apply only
  // the min_bids filter, which has visible effect.
  const filtered = COMPETITORS.filter((row) => row.bid_count >= params.minBids);
  return delay(filtered);
}

export async function mockFetchOpportunityGaps(
  params: OpportunityGapsParams,
): Promise<OpportunityRow[]> {
  const filtered = OPPORTUNITY_GAPS.filter(
    (row) =>
      row.avg_low_bid >= params.bidMin && row.avg_low_bid <= params.bidMax,
  );
  return delay(filtered);
}

export async function mockFetchBidCalibration(
  params: BidCalibrationParams,
): Promise<CalibrationPoint[]> {
  // Calibration is keyed by the contractor-name match. Mock dataset
  // is VanCon-only; if the caller asks for someone else, return empty
  // so the UI exercises the empty state.
  const match = params.contractorNameMatch.toLowerCase().trim();
  if (!match || match.includes("van con") || match.includes("vancon")) {
    return delay([...CALIBRATION]);
  }
  return delay([]);
}

// ── Toggle ──────────────────────────────────────────────────────────

/**
 * Reads `VITE_USE_MOCK_DATA` at module load. Vite inlines this as a
 * literal at build time, so the dead branch is tree-shaken in prod.
 */
export const USE_MOCK_DATA: boolean =
  import.meta.env.VITE_USE_MOCK_DATA === "true";
