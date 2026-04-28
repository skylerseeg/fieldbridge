import { api } from "@/lib/api";

/**
 * Typed client for the FastAPI bids module.
 *
 * Mirrors `backend/app/modules/bids/schema.py` 1:1. Each row is one
 * (job, bid_date) pair from `mart_bids_history` — VanCon's bid (or
 * decision not to bid), the competitor range, and the outcome.
 *
 * Three orthogonal classifications surface here:
 *   - **Outcome** — won / lost / no_bid / unknown.
 *   - **Margin tier** — how close VanCon came to the low bid
 *     (`winner` / `close` / `moderate` / `wide` / `unknown`).
 *   - **Competition tier** — bidder-density bucket
 *     (`solo` / `light` / `typical` / `crowded` / `unknown`).
 *
 * Mounted at `/api/bids` (NOT `/api/v1/bids`) — see `app/main.py`.
 */

const BASE = "/api/bids";

// ── Enums ────────────────────────────────────────────────────────────

export type BidOutcome = "won" | "lost" | "no_bid" | "unknown";

export type MarginTier =
  | "winner"
  | "close"
  | "moderate"
  | "wide"
  | "unknown";

export type CompetitionTier =
  | "solo"
  | "light"
  | "typical"
  | "crowded"
  | "unknown";

export type SortField =
  | "bid_date"
  | "job"
  | "vancon"
  | "low"
  | "rank"
  | "number_bidders"
  | "percent_over"
  | "lost_by";

export type SortDir = "asc" | "desc";

// ── List ─────────────────────────────────────────────────────────────

export interface BidListRow {
  id: string;
  job: string;
  bid_date: string;

  was_bid: boolean;
  owner: string | null;
  bid_type: string | null;
  county: string | null;
  estimator: string | null;

  vancon: number | null;
  low: number | null;
  high: number | null;
  engineer_estimate: string | null;

  rank: number | null;
  number_bidders: number | null;
  lost_by: number | null;
  percent_over: number | null;

  outcome: BidOutcome;
  margin_tier: MarginTier;
  competition_tier: CompetitionTier;
}

export interface BidListResponse {
  total: number;
  page: number;
  page_size: number;
  sort_by: string;
  sort_dir: SortDir;
  items: BidListRow[];
}

export interface ListParams {
  page?: number;
  page_size?: number;
  sort_by?: SortField;
  sort_dir?: SortDir;
  outcome?: BidOutcome;
  margin_tier?: MarginTier;
  competition_tier?: CompetitionTier;
  bid_type?: string;
  estimator?: string;
  county?: string;
  search?: string;
  close_max?: number;
  moderate_max?: number;
  light_max?: number;
  typical_max?: number;
}

// ── Summary ──────────────────────────────────────────────────────────

export interface BidsSummary {
  total_bids: number;
  bids_submitted: number;
  no_bids: number;
  bids_won: number;
  bids_lost: number;
  unknown_outcome: number;

  win_rate: number;

  total_vancon_bid_amount: number;
  total_vancon_won_amount: number;
  avg_vancon_bid: number;
  median_number_bidders: number | null;

  distinct_estimators: number;
  distinct_owners: number;
  distinct_counties: number;
  distinct_bid_types: number;

  outlook_count: number;
}

// ── Insights ─────────────────────────────────────────────────────────

export interface OutcomeBreakdown {
  won: number;
  lost: number;
  no_bid: number;
  unknown: number;
}

export interface MarginTierBreakdown {
  winner: number;
  close: number;
  moderate: number;
  wide: number;
  unknown: number;
}

export interface CompetitionTierBreakdown {
  solo: number;
  light: number;
  typical: number;
  crowded: number;
  unknown: number;
}

export interface WinRateBySegmentRow {
  segment: string;
  submitted: number;
  won: number;
  lost: number;
  unknown: number;
  win_rate: number;
  total_vancon_won_amount: number;
}

export interface NearMissRow {
  id: string;
  job: string;
  bid_date: string;
  vancon: number | null;
  low: number | null;
  lost_by: number | null;
  percent_over: number | null;
  estimator: string | null;
}

export interface BigWinRow {
  id: string;
  job: string;
  bid_date: string;
  vancon: number;
  owner: string | null;
  bid_type: string | null;
  estimator: string | null;
}

export interface RiskFlagFrequencyRow {
  flag: string;
  count: number;
  win_rate: number;
}

export interface BidsInsights {
  outcome_breakdown: OutcomeBreakdown;
  margin_tier_breakdown: MarginTierBreakdown;
  competition_tier_breakdown: CompetitionTierBreakdown;
  win_rate_by_bid_type: WinRateBySegmentRow[];
  win_rate_by_estimator: WinRateBySegmentRow[];
  win_rate_by_county: WinRateBySegmentRow[];
  near_misses: NearMissRow[];
  big_wins: BigWinRow[];
  risk_flag_frequency: RiskFlagFrequencyRow[];
}

// ── Detail (used by future row drill-down) ───────────────────────────

export interface CompetitorBidSlot {
  slot: number;
  competitor: string | null;
  amount: number | null;
  won_amount: number | null;
}

export interface BidDetail {
  id: string;
  job: string;
  bid_date: string;

  was_bid: boolean;
  owner: string | null;
  bid_type: string | null;
  county: string | null;
  estimator: string | null;

  vancon: number | null;
  low: number | null;
  high: number | null;
  engineer_estimate: string | null;

  rank: number | null;
  number_bidders: number | null;
  lost_by: number | null;
  percent_over: number | null;

  outcome: BidOutcome;
  margin_tier: MarginTier;
  competition_tier: CompetitionTier;

  labor_cost_factor: number | null;
  avg_mark_up_pct: number | null;
  mark_up: number | null;
  overhead_add_on: number | null;
  equip_op_exp: number | null;
  co_equip: number | null;

  completion_date: string | null;
  notice_to_proceed_date: string | null;

  pq: boolean | null;
  db_wages: boolean | null;
  plan_source: string | null;

  risk_flags: string[];
  competitors: CompetitorBidSlot[];
}

// ── Fetchers ─────────────────────────────────────────────────────────

export async function fetchBidsSummary(): Promise<BidsSummary> {
  const { data } = await api.get<BidsSummary>(`${BASE}/summary`);
  return data;
}

export async function fetchBidsList(
  params: ListParams,
): Promise<BidListResponse> {
  const { data } = await api.get<BidListResponse>(`${BASE}/list`, {
    params,
  });
  return data;
}

export async function fetchBidsInsights(
  topN = 10,
): Promise<BidsInsights> {
  const { data } = await api.get<BidsInsights>(`${BASE}/insights`, {
    params: { top_n: topN },
  });
  return data;
}

export async function fetchBidDetail(bidId: string): Promise<BidDetail> {
  const { data } = await api.get<BidDetail>(
    `${BASE}/${encodeURIComponent(bidId)}`,
  );
  return data;
}
