import { api } from "@/lib/api";

/**
 * Typed client for the FastAPI project_search module.
 *
 * ⚠ SPEC-FIRST — no `backend/app/modules/project_search/` mart
 * exists yet. This file defines the contract the backend must
 * implement to feed the Phase 5 page; until then every fetch will
 * 404 in dev. The legacy ChromaDB-backed search lives behind
 * `backend/app/services/project_memory/` but is not exposed under a
 * Phase-5-shaped HTTP surface — different prefix, different shape,
 * no list/summary/insights companions.
 *
 * One row per **indexed document chunk** in ChromaDB that matches
 * the current query (or, when no query is given, the latest content
 * for the active project filter). Three orthogonal classifications
 * surface here:
 *   - **DocType** — `email` / `bid_pdf` / `proposal` / `drawing` /
 *     `rfi` / `change_order` / `work_order` / `photo` / `transcript`
 *     / `note` / `other` — the ingestion source class.
 *   - **RelevanceLabel** — `unlabeled` / `useful` / `not_relevant` /
 *     `pinned` — user-supplied feedback signal that flows back into
 *     the embeddings layer.
 *   - **IndexStatus** — `fresh` / `stale` / `missing` — derived from
 *     `indexed_at` vs. `created_at`; used in the index-health
 *     insight rollup, not on every row.
 *
 * Mutations (`mark_useful`, `mark_not_relevant`, `pin`, `clear`)
 * update only the row's `relevance_label` field, so the page can
 * apply optimistic updates safely.
 *
 * Mounted at `/api/project-search` (NOT `/api/v1/...`) — see the
 * other Phase 5 marts (`/api/bids`, `/api/cost-coding`,
 * `/api/proposals`, `/api/recommendations`,
 * `/api/predictive-maintenance`). Note the hyphen even though the
 * Python package uses an underscore.
 */

const BASE = "/api/project-search";

// ── Enums ────────────────────────────────────────────────────────────

export type DocType =
  | "email"
  | "bid_pdf"
  | "proposal"
  | "drawing"
  | "rfi"
  | "change_order"
  | "work_order"
  | "photo"
  | "transcript"
  | "note"
  | "other";

export type RelevanceLabel =
  | "unlabeled"
  | "useful"
  | "not_relevant"
  | "pinned";

export type IndexStatus = "fresh" | "stale" | "missing";

export type SortField =
  | "relevance"
  | "created_at"
  | "indexed_at"
  | "project_label"
  | "doc_type";

export type SortDir = "asc" | "desc";

// ── List ─────────────────────────────────────────────────────────────

export interface SearchResultRow {
  id: string;

  /** The chunk's parent document (e.g. an email message id, a PDF doc id). */
  document_id: string;
  /** Stable index of the chunk inside the parent document. */
  chunk_index: number;

  project_id: string | null;
  project_label: string | null;

  doc_type: DocType;
  relevance_label: RelevanceLabel;

  /** Human-readable headline (subject, filename, or first sentence). */
  title: string;
  /** Up to ~600-char excerpt with the matched span emphasized backend-side. */
  snippet: string;

  /**
   * Cosine-similarity-derived relevance score in [0, 1]. `null` when
   * the result was returned via filter-only browse (no query).
   */
  score: number | null;

  /** Original-source URL (e.g. M365 deep link, blob SAS, drawing viewer). */
  source_url: string | null;
  /** Optional file-type hint for an icon (`pdf`, `png`, `eml`, …). */
  source_kind: string | null;

  /** ISO — when the document itself was authored. */
  created_at: string;
  /** ISO — when the chunk was last embedded into ChromaDB. */
  indexed_at: string;

  /** Days since `indexed_at`. */
  index_age_days: number;
}

export interface SearchListResponse {
  total: number;
  page: number;
  page_size: number;
  sort_by: string;
  sort_dir: SortDir;
  /** Round-trip latency for the underlying vector search, milliseconds. */
  took_ms: number;
  /** Echo of the query string the backend used (after rewriting). */
  effective_query: string | null;
  items: SearchResultRow[];
}

export interface ListParams {
  page?: number;
  page_size?: number;
  sort_by?: SortField;
  sort_dir?: SortDir;
  /** Free-text query — empty/undefined means filter-only browse. */
  q?: string;
  project_id?: string;
  doc_type?: DocType;
  relevance_label?: RelevanceLabel;
  /** ISO date — only return docs `created_at >= date_from`. */
  date_from?: string;
  /** ISO date — only return docs `created_at <= date_to`. */
  date_to?: string;
}

// ── Summary ──────────────────────────────────────────────────────────

export interface ProjectSearchSummary {
  total_indexed_documents: number;
  total_indexed_chunks: number;

  distinct_projects: number;
  distinct_doc_types: number;

  /** ISO — most-recent `indexed_at` across the corpus, null if empty. */
  last_indexed_at: string | null;
  /** Days since `last_indexed_at`, null if empty. */
  index_age_days: number | null;

  /** Documents queued for indexing but not yet embedded. */
  pending_index_count: number;
  /** Documents whose source was modified after their last embedding. */
  stale_index_count: number;

  /** Distinct queries observed in the last 7 days. */
  recent_query_count_7d: number;
  /** Trailing-7d average over `took_ms`. */
  avg_query_latency_ms: number | null;

  pinned_count: number;
  useful_count: number;
  not_relevant_count: number;
  unlabeled_count: number;
}

// ── Insights ─────────────────────────────────────────────────────────

export interface DocTypeBreakdown {
  email: number;
  bid_pdf: number;
  proposal: number;
  drawing: number;
  rfi: number;
  change_order: number;
  work_order: number;
  photo: number;
  transcript: number;
  note: number;
  other: number;
}

export interface RelevanceLabelBreakdown {
  unlabeled: number;
  useful: number;
  not_relevant: number;
  pinned: number;
}

export interface IndexAgingBreakdown {
  fresh: number; // <=7 days since indexed_at
  mature: number; // 8–30 days
  stale: number; // >30 days
}

export interface ProjectCoverageRow {
  project_id: string;
  project_label: string;
  document_count: number;
  chunk_count: number;
  /** Days since the most recent `indexed_at` for this project. */
  last_indexed_age_days: number;
  status: IndexStatus;
}

export interface DocTypeImpactRow {
  doc_type: DocType;
  document_count: number;
  /** Sum of `useful_count + pinned_count` for this doc type. */
  signal_count: number;
}

export interface TopQueryRow {
  query: string;
  count: number;
  /** Average `took_ms` across the runs. */
  avg_latency_ms: number;
}

export interface PinnedResultRow {
  id: string;
  title: string;
  doc_type: DocType;
  project_label: string | null;
  pinned_at: string; // ISO
}

export interface RecentIndexedRow {
  id: string;
  title: string;
  doc_type: DocType;
  project_label: string | null;
  indexed_at: string; // ISO
}

export interface ProjectSearchInsights {
  doc_type_breakdown: DocTypeBreakdown;
  relevance_breakdown: RelevanceLabelBreakdown;
  aging_breakdown: IndexAgingBreakdown;
  project_coverage: ProjectCoverageRow[];
  doc_type_impact: DocTypeImpactRow[];
  top_queries: TopQueryRow[];
  top_pinned: PinnedResultRow[];
  recent_indexed: RecentIndexedRow[];
}

// ── Detail ───────────────────────────────────────────────────────────

export interface SearchResultEvidence {
  label: string;
  value: string;
  link: string | null;
}

export interface SearchResultHistoryEntry {
  at: string; // ISO
  label: RelevanceLabel;
  note: string | null;
}

export interface SearchResultDetail {
  id: string;

  document_id: string;
  chunk_index: number;

  project_id: string | null;
  project_label: string | null;

  doc_type: DocType;
  relevance_label: RelevanceLabel;

  title: string;
  /** Full chunk text (not truncated, no markup). */
  body: string;
  /** Free-form description of the parent document. */
  description: string;

  score: number | null;
  source_url: string | null;
  source_kind: string | null;

  created_at: string;
  indexed_at: string;
  index_age_days: number;

  /** Up to N nearest-neighbor chunks for this result, by cosine similarity. */
  related: {
    id: string;
    title: string;
    doc_type: DocType;
    score: number;
  }[];

  evidence: SearchResultEvidence[];
  history: SearchResultHistoryEntry[];
}

// ── Mutation bodies ──────────────────────────────────────────────────

export interface MarkUsefulBody {
  note?: string;
}

export interface MarkNotRelevantBody {
  reason?: string;
}

export interface PinBody {
  note?: string;
}

export interface ClearLabelBody {
  reason?: string;
}

// ── Fetchers ─────────────────────────────────────────────────────────

export async function fetchProjectSearchSummary(): Promise<ProjectSearchSummary> {
  const { data } = await api.get<ProjectSearchSummary>(`${BASE}/summary`);
  return data;
}

export async function fetchProjectSearchList(
  params: ListParams,
): Promise<SearchListResponse> {
  const { data } = await api.get<SearchListResponse>(`${BASE}/list`, {
    params,
  });
  return data;
}

export async function fetchProjectSearchInsights(
  topN = 10,
): Promise<ProjectSearchInsights> {
  const { data } = await api.get<ProjectSearchInsights>(`${BASE}/insights`, {
    params: { top_n: topN },
  });
  return data;
}

export async function fetchSearchResultDetail(
  resultId: string,
): Promise<SearchResultDetail> {
  const { data } = await api.get<SearchResultDetail>(
    `${BASE}/${encodeURIComponent(resultId)}`,
  );
  return data;
}

// ── Mutations ────────────────────────────────────────────────────────

export async function markResultUseful(
  id: string,
  body: MarkUsefulBody = {},
): Promise<SearchResultDetail> {
  const { data } = await api.post<SearchResultDetail>(
    `${BASE}/${encodeURIComponent(id)}/useful`,
    body,
  );
  return data;
}

export async function markResultNotRelevant(
  id: string,
  body: MarkNotRelevantBody = {},
): Promise<SearchResultDetail> {
  const { data } = await api.post<SearchResultDetail>(
    `${BASE}/${encodeURIComponent(id)}/not_relevant`,
    body,
  );
  return data;
}

export async function pinResult(
  id: string,
  body: PinBody = {},
): Promise<SearchResultDetail> {
  const { data } = await api.post<SearchResultDetail>(
    `${BASE}/${encodeURIComponent(id)}/pin`,
    body,
  );
  return data;
}

export async function clearResultLabel(
  id: string,
  body: ClearLabelBody = {},
): Promise<SearchResultDetail> {
  const { data } = await api.post<SearchResultDetail>(
    `${BASE}/${encodeURIComponent(id)}/clear`,
    body,
  );
  return data;
}
