import { api } from "@/lib/api";

/**
 * Typed client for the FastAPI activity_feed module.
 *
 * Mirrors `backend/app/modules/activity_feed/schema.py` 1:1.
 * Backend is the source of truth — keep these in sync when the
 * Pydantic models there change.
 *
 * Mounted at the bare `/api/activity-feed` prefix in `app/main.py`
 * (NOT under `/api/v1`).
 */

const BASE = "/api/activity-feed";

// ── Enums ────────────────────────────────────────────────────────────

export type ActivityKind =
  | "ingest_ok"
  | "ingest_partial"
  | "ingest_failed"
  | "agent_call"
  | "insight_generated";

export type ActivitySeverity = "critical" | "warning" | "info";

// ── Feed ─────────────────────────────────────────────────────────────

export interface ActivityEvent {
  /** Composite "{source}:{uuid}". Stable across reloads, opaque to UI. */
  id: string;
  kind: ActivityKind;
  severity: ActivitySeverity;
  /** ISO 8601, UTC. */
  occurred_at: string;
  /** Agent slug for agent_call / insight_generated; null otherwise. */
  actor: string | null;
  /** Free-form entity hint (job, mart, module). Null when unknown. */
  entity_ref: string | null;
  summary: string;
  /**
   * Source-specific extras. Schema varies by `kind` — treat as opaque.
   * Common keys per kind:
   *   ingest_*       — job_name, source_file, target_table, status,
   *                    rows_read, rows_written, rows_skipped,
   *                    duration_ms, errors?
   *   agent_call     — agent, model, input_tokens, output_tokens,
   *                    cache_*_tokens, cost_usd, job_number?,
   *                    equipment_id?, user_id?
   *   insight_generated — module, revision_token, model,
   *                       input_tokens, output_tokens, expires_at
   */
  detail: Record<string, unknown>;
}

export interface ActivityFeed {
  as_of: string;
  /** Sorted by (severity desc, occurred_at desc). Capped at top_n. */
  items: ActivityEvent[];
  total_returned: number;
  total_matching: number;
}

// ── Summary ──────────────────────────────────────────────────────────

export interface ActivityCounts {
  critical: number;
  warning: number;
  info: number;
}

export interface ActivityKindCounts {
  ingest_ok: number;
  ingest_partial: number;
  ingest_failed: number;
  agent_call: number;
  insight_generated: number;
}

export interface ActivitySummary {
  as_of: string;
  last_24h: number;
  last_7d: number;
  total: number;
  by_severity: ActivityCounts;
  by_kind: ActivityKindCounts;
}

// ── Fetchers ─────────────────────────────────────────────────────────

export interface FetchEventsParams {
  topN?: number;
  lookbackDays?: number;
  /** ISO timestamp; overrides lookbackDays when set. */
  since?: string;
  kind?: ActivityKind;
  severity?: ActivitySeverity;
}

export async function fetchActivityFeed(
  params: FetchEventsParams = {},
): Promise<ActivityFeed> {
  const { topN, lookbackDays, since, kind, severity } = params;
  const { data } = await api.get<ActivityFeed>(`${BASE}/events`, {
    params: {
      top_n: topN,
      lookback_days: lookbackDays,
      since,
      kind,
      severity,
    },
  });
  return data;
}

export async function fetchActivitySummary(
  lookbackDays?: number,
): Promise<ActivitySummary> {
  const { data } = await api.get<ActivitySummary>(`${BASE}/summary`, {
    params: { lookback_days: lookbackDays },
  });
  return data;
}
