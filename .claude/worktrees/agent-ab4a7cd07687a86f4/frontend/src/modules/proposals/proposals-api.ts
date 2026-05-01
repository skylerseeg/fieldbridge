import { api } from "@/lib/api";

/**
 * Typed client for the FastAPI proposals module.
 *
 * Mirrors `backend/app/modules/proposals/schema.py` 1:1. Each row is
 * one proposal header from `mart_proposals`, keyed on
 * `(job, owner, bid_type)`. Two derived classifications surface here:
 *
 *   - **BidTypeCategory** — keyword bucketing of the free-form
 *     `bid_type` (pressurized / structures / concrete / earthwork /
 *     other).
 *   - **GeographyTier** — `in_state` / `out_of_state` / `unknown`
 *     against the tenant's primary state (default `UT`).
 *
 * Line items live in a separate mart that does not yet link back to
 * an individual proposal; they surface only as tenant-wide aggregates
 * via `/summary` + `/insights`.
 *
 * Mounted at `/api/proposals` (NOT `/api/v1/proposals`) — see
 * `app/main.py`.
 */

const BASE = "/api/proposals";

// ── Enums ────────────────────────────────────────────────────────────

export type BidTypeCategory =
  | "pressurized"
  | "structures"
  | "concrete"
  | "earthwork"
  | "other";

export type GeographyTier = "in_state" | "out_of_state" | "unknown";

export type SortField = "job" | "owner" | "bid_type" | "county";

export type SortDir = "asc" | "desc";

// ── List ─────────────────────────────────────────────────────────────

export interface ProposalListRow {
  id: string;
  job: string;
  owner: string;
  bid_type: string;
  county: string | null;
  state_code: string | null;

  bid_type_category: BidTypeCategory;
  geography_tier: GeographyTier;
}

export interface ProposalListResponse {
  total: number;
  page: number;
  page_size: number;
  sort_by: string;
  sort_dir: SortDir;
  items: ProposalListRow[];
}

export interface ListParams {
  page?: number;
  page_size?: number;
  sort_by?: SortField;
  sort_dir?: SortDir;
  bid_type_category?: BidTypeCategory;
  geography_tier?: GeographyTier;
  bid_type?: string;
  owner?: string;
  county?: string;
  state_code?: string;
  search?: string;
  primary_state?: string;
}

// ── Summary ──────────────────────────────────────────────────────────

export interface ProposalsSummary {
  total_proposals: number;
  distinct_owners: number;
  distinct_bid_types: number;
  distinct_counties: number;
  distinct_states: number;

  in_state_proposals: number;
  out_of_state_proposals: number;
  unknown_geography_proposals: number;

  total_line_items: number;
  line_items_with_competitor: number;
  distinct_competitors: number;

  total_city_budget: number;
  avg_city_budget: number;
}

// ── Insights ─────────────────────────────────────────────────────────

export interface BidTypeCategoryBreakdown {
  pressurized: number;
  structures: number;
  concrete: number;
  earthwork: number;
  other: number;
}

export interface GeographyTierBreakdown {
  in_state: number;
  out_of_state: number;
  unknown: number;
}

export interface SegmentCountRow {
  segment: string;
  count: number;
}

export interface CompetitorFrequencyRow {
  competitor: string;
  line_item_count: number;
}

export interface FeeStatsRow {
  fee: string;
  count: number;
  min_value: number | null;
  max_value: number | null;
  avg_value: number | null;
}

export interface ProposalsInsights {
  bid_type_category_breakdown: BidTypeCategoryBreakdown;
  geography_tier_breakdown: GeographyTierBreakdown;
  top_owners: SegmentCountRow[];
  top_bid_types: SegmentCountRow[];
  top_counties: SegmentCountRow[];
  top_states: SegmentCountRow[];
  competitor_frequency: CompetitorFrequencyRow[];
  fee_statistics: FeeStatsRow[];
}

// ── Detail (used by future row drill-down) ───────────────────────────

export interface ProposalDetail {
  id: string;
  job: string;
  owner: string;
  bid_type: string;
  county: string | null;
  state_code: string | null;
  bid_type_category: BidTypeCategory;
  geography_tier: GeographyTier;
}

// ── Fetchers ─────────────────────────────────────────────────────────

export async function fetchProposalsSummary(): Promise<ProposalsSummary> {
  const { data } = await api.get<ProposalsSummary>(`${BASE}/summary`);
  return data;
}

export async function fetchProposalsList(
  params: ListParams,
): Promise<ProposalListResponse> {
  const { data } = await api.get<ProposalListResponse>(`${BASE}/list`, {
    params,
  });
  return data;
}

export async function fetchProposalsInsights(
  topN = 10,
): Promise<ProposalsInsights> {
  const { data } = await api.get<ProposalsInsights>(`${BASE}/insights`, {
    params: { top_n: topN },
  });
  return data;
}

export async function fetchProposalDetail(
  proposalId: string,
): Promise<ProposalDetail> {
  const { data } = await api.get<ProposalDetail>(
    `${BASE}/${encodeURIComponent(proposalId)}`,
  );
  return data;
}
