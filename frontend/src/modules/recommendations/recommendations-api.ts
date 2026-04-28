import { api } from "@/lib/api";

/**
 * Typed client for the FastAPI recommendations module.
 *
 * ⚠ SPEC-FIRST — no `backend/app/modules/recommendations/schema.py`
 * exists yet. This file defines the contract the backend must
 * implement to feed the Phase 5 recommendations page; until then,
 * every fetch will 404 in dev. The legacy AI agent at
 * `/api/v1/dashboard/recommendations` is **not** the source — that
 * endpoint returns a free-form blob and lives behind a different
 * prefix.
 *
 * One row per AI-surfaced recommendation. Three orthogonal axes:
 *   - **Priority** — `p1` / `p2` / `p3` (criticality).
 *   - **Category** — domain bucket the recommendation lives in
 *     (financial / fleet / safety / operations / bids / proposals).
 *   - **Status** — workflow state (open / snoozed / dismissed / done).
 *
 * Mutations (`dismiss`, `snooze`, `mark_done`) update only the
 * `status` field on the row, so the page can apply optimistic
 * updates safely.
 *
 * Mounted at `/api/recommendations` (NOT `/api/v1/recommendations`) to
 * match the other Phase 5 marts (`/api/bids`, `/api/cost-coding`,
 * `/api/proposals`).
 */

const BASE = "/api/recommendations";

// ── Enums ────────────────────────────────────────────────────────────

export type Priority = "p1" | "p2" | "p3";

export type RecCategory =
  | "financial"
  | "fleet"
  | "safety"
  | "operations"
  | "bids"
  | "proposals";

export type RecStatus = "open" | "snoozed" | "dismissed" | "done";

export type SortField =
  | "priority"
  | "created_at"
  | "impact_dollars"
  | "category"
  | "source"
  | "title";

export type SortDir = "asc" | "desc";

// ── List ─────────────────────────────────────────────────────────────

export interface RecommendationListRow {
  id: string;
  title: string;
  summary: string;

  priority: Priority;
  category: RecCategory;
  status: RecStatus;

  source: string; // module slug — e.g. "bids", "cost_coding", "fleet_pnl"
  entity_type: string | null; // "equipment", "job", "bid", …
  entity_label: string | null;

  impact_dollars: number | null;
  action: string;
  owner_role: string | null;

  created_at: string; // ISO
  updated_at: string; // ISO
  snoozed_until: string | null; // ISO, only when status === "snoozed"

  age_days: number;
}

export interface RecommendationListResponse {
  total: number;
  page: number;
  page_size: number;
  sort_by: string;
  sort_dir: SortDir;
  items: RecommendationListRow[];
}

export interface ListParams {
  page?: number;
  page_size?: number;
  sort_by?: SortField;
  sort_dir?: SortDir;
  priority?: Priority;
  category?: RecCategory;
  status?: RecStatus;
  source?: string;
  search?: string;
  min_impact?: number;
}

// ── Summary ──────────────────────────────────────────────────────────

export interface RecommendationsSummary {
  total_recommendations: number;

  open_count: number;
  snoozed_count: number;
  dismissed_count: number;
  done_count: number;

  p1_count: number;
  p2_count: number;
  p3_count: number;
  open_p1_count: number;

  total_potential_impact: number; // sum of impact_dollars across `open`
  average_age_days: number | null; // avg age of open recommendations
  oldest_open_age_days: number | null;

  distinct_categories: number;
  distinct_sources: number;
}

// ── Insights ─────────────────────────────────────────────────────────

export interface PriorityBreakdown {
  p1: number;
  p2: number;
  p3: number;
}

export interface RecStatusBreakdown {
  open: number;
  snoozed: number;
  dismissed: number;
  done: number;
}

export interface RecCategoryBreakdown {
  financial: number;
  fleet: number;
  safety: number;
  operations: number;
  bids: number;
  proposals: number;
}

export interface AgingBreakdown {
  fresh: number; // <7 days
  mature: number; // 7–30 days
  stale: number; // >30 days
}

export interface SegmentCountRow {
  segment: string;
  count: number;
}

export interface CategoryImpactRow {
  category: RecCategory;
  open_count: number;
  total_impact: number;
}

export interface TopRecRow {
  id: string;
  title: string;
  priority: Priority;
  category: RecCategory;
  source: string;
  impact_dollars: number | null;
  age_days: number;
}

export interface ResolvedRecRow {
  id: string;
  title: string;
  category: RecCategory;
  status: RecStatus; // dismissed | done
  resolved_at: string; // ISO
}

export interface RecommendationsInsights {
  priority_breakdown: PriorityBreakdown;
  status_breakdown: RecStatusBreakdown;
  category_breakdown: RecCategoryBreakdown;
  aging_breakdown: AgingBreakdown;
  top_sources: SegmentCountRow[];
  category_impact: CategoryImpactRow[];
  top_by_impact: TopRecRow[];
  recent_resolutions: ResolvedRecRow[];
}

// ── Detail ───────────────────────────────────────────────────────────

export interface RecommendationEvidence {
  label: string;
  value: string;
  link: string | null; // optional drill-down URL
}

export interface RecommendationHistoryEntry {
  at: string; // ISO
  status: RecStatus;
  note: string | null;
}

export interface RecommendationDetail {
  id: string;
  title: string;
  summary: string;
  description: string;

  priority: Priority;
  category: RecCategory;
  status: RecStatus;

  source: string;
  entity_type: string | null;
  entity_id: string | null;
  entity_label: string | null;

  impact_dollars: number | null;
  action: string;
  owner_role: string | null;

  created_at: string;
  updated_at: string;
  snoozed_until: string | null;
  age_days: number;

  evidence: RecommendationEvidence[];
  history: RecommendationHistoryEntry[];
}

// ── Mutation bodies ──────────────────────────────────────────────────

export interface DismissBody {
  reason?: string;
}

export interface SnoozeBody {
  /** ISO date — when the snooze should expire and status flip back to `open`. */
  until: string;
  reason?: string;
}

export interface DoneBody {
  note?: string;
}

// ── Fetchers ─────────────────────────────────────────────────────────

export async function fetchRecommendationsSummary(): Promise<RecommendationsSummary> {
  const { data } = await api.get<RecommendationsSummary>(`${BASE}/summary`);
  return data;
}

export async function fetchRecommendationsList(
  params: ListParams,
): Promise<RecommendationListResponse> {
  const { data } = await api.get<RecommendationListResponse>(`${BASE}/list`, {
    params,
  });
  return data;
}

export async function fetchRecommendationsInsights(
  topN = 10,
): Promise<RecommendationsInsights> {
  const { data } = await api.get<RecommendationsInsights>(`${BASE}/insights`, {
    params: { top_n: topN },
  });
  return data;
}

export async function fetchRecommendationDetail(
  recommendationId: string,
): Promise<RecommendationDetail> {
  const { data } = await api.get<RecommendationDetail>(
    `${BASE}/${encodeURIComponent(recommendationId)}`,
  );
  return data;
}

// ── Mutations ────────────────────────────────────────────────────────

export async function dismissRecommendation(
  id: string,
  body: DismissBody = {},
): Promise<RecommendationDetail> {
  const { data } = await api.post<RecommendationDetail>(
    `${BASE}/${encodeURIComponent(id)}/dismiss`,
    body,
  );
  return data;
}

export async function snoozeRecommendation(
  id: string,
  body: SnoozeBody,
): Promise<RecommendationDetail> {
  const { data } = await api.post<RecommendationDetail>(
    `${BASE}/${encodeURIComponent(id)}/snooze`,
    body,
  );
  return data;
}

export async function markRecommendationDone(
  id: string,
  body: DoneBody = {},
): Promise<RecommendationDetail> {
  const { data } = await api.post<RecommendationDetail>(
    `${BASE}/${encodeURIComponent(id)}/done`,
    body,
  );
  return data;
}
