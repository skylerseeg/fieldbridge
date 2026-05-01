import type {
  BidCalibrationParams,
  CalibrationPoint,
  CompetitorCurveRow,
  CompetitorCurvesParams,
  CountyGapDetailParams,
  CountyGapEvent,
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

// ── County gap detail ───────────────────────────────────────────────
//
// Per-event drill-in fixtures keyed by `${state}|${county}`. Numbers
// are illustrative — owner names and scope codes are realistic for the
// western heavy-civil market but not sourced from real bid tabs.
//
// Coverage: every (state, county) cell in OPPORTUNITY_GAPS gets at
// least 1 sample row so the drill page is never blank when the user
// clicks any of the top-N rows. Cells with higher missed_count get
// proportionally more sample events.

interface CountyGapKey {
  state: string;
  county: string;
}

function gapKey(k: CountyGapKey): string {
  return `${k.state}|${k.county}`;
}

const COUNTY_GAP_DETAIL: Record<string, CountyGapEvent[]> = {
  "ID|Ada": [
    {
      bid_event_id: "f1c2a4e8-1101-4a01-9000-aaaa00000001",
      project_title: "I-84, Eagle Rd to Garrity Blvd Pavement Rehabilitation",
      project_owner: "Idaho Transportation Department",
      solicitation_id: "ITD-25183",
      source_url: "https://apps.itd.idaho.gov/apps/contractors/abst25183.pdf",
      source_state: "ID",
      source_network: "state_dot_id",
      bid_open_date: "2026-04-15",
      location_state: "ID",
      location_county: "Ada",
      csi_codes: ["32 11 23", "31 23 16"],
      low_bidder_name: "Knife River Corporation - Northwest",
      low_bid_amount: 4_280_000,
    },
    {
      bid_event_id: "f1c2a4e8-1101-4a01-9000-aaaa00000002",
      project_title: "SH-44, State St to Linder Rd Widening",
      project_owner: "Idaho Transportation Department",
      solicitation_id: "ITD-24881",
      source_url: "https://apps.itd.idaho.gov/apps/contractors/abst24881.pdf",
      source_state: "ID",
      source_network: "state_dot_id",
      bid_open_date: "2026-03-04",
      location_state: "ID",
      location_county: "Ada",
      csi_codes: ["32 11 23", "33 41 00"],
      low_bidder_name: "Concrete Placing Co., Inc.",
      low_bid_amount: 1_840_000,
    },
    {
      bid_event_id: "f1c2a4e8-1101-4a01-9000-aaaa00000003",
      project_title: "Boise Airport Apron Reconstruction Phase 3",
      project_owner: "City of Boise (Boise Airport)",
      solicitation_id: "BOI-AIR-2026-04",
      source_url: "https://apps.itd.idaho.gov/apps/contractors/abst25011.pdf",
      source_state: "ID",
      source_network: "state_dot_id",
      bid_open_date: "2026-02-20",
      location_state: "ID",
      location_county: "Ada",
      csi_codes: ["32 12 16", "31 23 16"],
      low_bidder_name: "Sunroc Corporation",
      low_bid_amount: 3_120_000,
    },
    {
      bid_event_id: "f1c2a4e8-1101-4a01-9000-aaaa00000004",
      project_title: "Meridian Storm Drain Improvements - Locust Grove",
      project_owner: "City of Meridian",
      solicitation_id: "MER-2025-019",
      source_url: "https://apps.itd.idaho.gov/apps/contractors/abst24573.pdf",
      source_state: "ID",
      source_network: "state_dot_id",
      bid_open_date: "2025-11-12",
      location_state: "ID",
      location_county: "Ada",
      csi_codes: ["33 41 00"],
      low_bidder_name: "Knife River Corporation - Northwest",
      low_bid_amount: 920_000,
    },
    {
      bid_event_id: "f1c2a4e8-1101-4a01-9000-aaaa00000005",
      project_title: "US-20/26, Chinden Blvd Resurfacing",
      project_owner: "Idaho Transportation Department",
      solicitation_id: "ITD-24412",
      source_url: "https://apps.itd.idaho.gov/apps/contractors/abst24412.pdf",
      source_state: "ID",
      source_network: "state_dot_id",
      bid_open_date: "2025-09-08",
      location_state: "ID",
      location_county: "Ada",
      csi_codes: ["32 11 23"],
      low_bidder_name: "Concrete Placing Co., Inc.",
      low_bid_amount: 2_640_000,
    },
  ],
  "ID|Canyon": [
    {
      bid_event_id: "f1c2a4e8-1102-4a01-9000-aaaa00000010",
      project_title: "Caldwell Industrial Way Reconstruction",
      project_owner: "City of Caldwell",
      solicitation_id: "CALD-2026-007",
      source_url: "https://apps.itd.idaho.gov/apps/contractors/abst25022.pdf",
      source_state: "ID",
      source_network: "state_dot_id",
      bid_open_date: "2026-03-22",
      location_state: "ID",
      location_county: "Canyon",
      csi_codes: ["32 12 16", "31 23 16"],
      low_bidder_name: "Western Construction, Inc.",
      low_bid_amount: 1_120_000,
    },
    {
      bid_event_id: "f1c2a4e8-1102-4a01-9000-aaaa00000011",
      project_title: "SH-19, Wilder to Greenleaf Pavement Rehab",
      project_owner: "Idaho Transportation Department",
      solicitation_id: "ITD-24732",
      source_url: "https://apps.itd.idaho.gov/apps/contractors/abst24732.pdf",
      source_state: "ID",
      source_network: "state_dot_id",
      bid_open_date: "2025-12-05",
      location_state: "ID",
      location_county: "Canyon",
      csi_codes: ["32 11 23"],
      low_bidder_name: "Knife River Corporation - Northwest",
      low_bid_amount: 880_000,
    },
  ],
  "UT|Salt Lake": [
    {
      bid_event_id: "f1c2a4e8-1201-4a01-9000-aaaa00000020",
      project_title: "I-15, 600 N to 12300 S Pavement Preservation",
      project_owner: "Utah Department of Transportation",
      solicitation_id: "UDOT-S-N1234(56)",
      source_url: "https://apps.itd.idaho.gov/apps/contractors/abst25101.pdf",
      source_state: "ID",
      source_network: "state_dot_id",
      bid_open_date: "2026-04-02",
      location_state: "UT",
      location_county: "Salt Lake",
      csi_codes: ["32 11 23", "31 23 16"],
      low_bidder_name: "Granite Construction",
      low_bid_amount: 1_560_000,
    },
    {
      bid_event_id: "f1c2a4e8-1201-4a01-9000-aaaa00000021",
      project_title: "SR-201 Bridge Deck Rehabilitation",
      project_owner: "Utah Department of Transportation",
      solicitation_id: "UDOT-F-201(78)",
      source_url: "https://apps.itd.idaho.gov/apps/contractors/abst24990.pdf",
      source_state: "ID",
      source_network: "state_dot_id",
      bid_open_date: "2026-02-11",
      location_state: "UT",
      location_county: "Salt Lake",
      csi_codes: ["33 11 00"],
      low_bidder_name: "W. W. Clyde & Co.",
      low_bid_amount: 1_240_000,
    },
  ],
};

function mockCountyDetailFor(state: string, county: string): CountyGapEvent[] {
  // Direct hit on a curated cell — return as-is.
  const direct = COUNTY_GAP_DETAIL[gapKey({ state: state.toUpperCase(), county })];
  if (direct) return direct;

  // Fallback: synthesize 2 illustrative rows so the drill page never
  // shows blank for an unfamiliar (state, county) combo. Operator
  // notes: the real backend returns [] in this case; we choose to
  // synthesize for offline UI dev so empty-state UX gets exercised
  // separately via the explicit "ZZ|Ghost" affordance below.
  if (state.toUpperCase() === "ZZ") return [];

  const padState = state.toUpperCase().padEnd(2, "X").slice(0, 2);
  return [
    {
      bid_event_id: `mock-${padState}-${county}-001`,
      project_title: `Sample paving contract — ${county}`,
      project_owner: "(mock) State DOT",
      solicitation_id: null,
      source_url: "https://example.invalid/sample-bid-abstract.pdf",
      source_state: padState,
      source_network: "state_dot_mock",
      bid_open_date: "2026-01-15",
      location_state: padState,
      location_county: county,
      csi_codes: ["32 11 23"],
      low_bidder_name: "Sample Constructor LLC",
      low_bid_amount: 1_200_000,
    },
    {
      bid_event_id: `mock-${padState}-${county}-002`,
      project_title: `Sample utility contract — ${county}`,
      project_owner: "(mock) Local agency",
      solicitation_id: null,
      source_url: "https://example.invalid/sample-bid-abstract-2.pdf",
      source_state: padState,
      source_network: "state_dot_mock",
      bid_open_date: "2025-09-22",
      location_state: padState,
      location_county: county,
      csi_codes: ["33 41 00"],
      low_bidder_name: "Sample Utility Co.",
      low_bid_amount: 720_000,
    },
  ];
}

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

export async function mockFetchCountyGapDetail(
  params: CountyGapDetailParams,
): Promise<CountyGapEvent[]> {
  const events = mockCountyDetailFor(params.state, params.county);
  // Honor the bid-amount filter so the UI's filter knobs feel real.
  const filtered = events.filter(
    (row) =>
      row.low_bid_amount >= params.bidMin && row.low_bid_amount <= params.bidMax,
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
