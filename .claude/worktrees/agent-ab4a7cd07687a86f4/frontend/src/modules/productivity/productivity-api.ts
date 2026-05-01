import { api } from "@/lib/api";

/**
 * Typed client for the FastAPI productivity module.
 *
 * Mirrors `backend/app/modules/productivity/schema.py` 1:1. Mounted at
 * `/api/productivity` — see `app/main.py`.
 */

const BASE = "/api/productivity";

// ── Enums ────────────────────────────────────────────────────────────

export type ResourceKind = "labor" | "equipment";

export type PhaseStatus =
  | "over_budget"
  | "behind_pace"
  | "on_track"
  | "complete"
  | "unknown";

// ── Phase / job detail ────────────────────────────────────────────────

export interface PhasePerf {
  resource_kind: ResourceKind;
  actual_hours: number | null;
  est_hours: number | null;
  variance_hours: number | null;
  percent_used: number | null;
  percent_complete: number | null;
  units_complete: number | null;
  actual_units: number | null;
  budget_hours: number | null;
  projected_hours: number | null;
  schedule_performance_index: number | null;
  status: PhaseStatus;
}

export interface JobPhaseRow {
  phase_id: string;
  phase: string;
  project_end_date: string | null;
  labor: PhasePerf | null;
  equipment: PhasePerf | null;
  worst_status: PhaseStatus;
}

export interface JobHoursRollup {
  actual_hours: number;
  est_hours: number;
  variance_hours: number;
  percent_used: number | null;
}

export interface JobProductivityDetail {
  id: string;
  job: string;
  project_end_date: string | null;
  phases: JobPhaseRow[];
  labor_rollup: JobHoursRollup | null;
  equipment_rollup: JobHoursRollup | null;
  phases_complete: number;
  phases_on_track: number;
  phases_behind_pace: number;
  phases_over_budget: number;
  phases_unknown: number;
}

// ── Summary ───────────────────────────────────────────────────────────

export interface ResourceTotals {
  resource_kind: ResourceKind;
  phases: number;
  actual_hours: number;
  est_hours: number;
  percent_used: number | null;
  avg_percent_complete: number;
}

export interface ProductivitySummary {
  total_jobs: number;
  total_phases: number;
  labor_totals: ResourceTotals;
  equipment_totals: ResourceTotals;
  combined_actual_hours: number;
  combined_est_hours: number;
  combined_percent_used: number | null;
  phases_complete: number;
  phases_on_track: number;
  phases_behind_pace: number;
  phases_over_budget: number;
  phases_unknown: number;
  pct_complete: number;
  pct_on_track: number;
  pct_behind_pace: number;
  pct_over_budget: number;
  pct_unknown: number;
}

// ── Attention ────────────────────────────────────────────────────────

export interface AttentionRow {
  job_id: string;
  job: string;
  phase_id: string;
  phase: string;
  resource_kind: ResourceKind;
  status: PhaseStatus;
  actual_hours: number | null;
  est_hours: number | null;
  variance_hours: number | null;
  percent_used: number | null;
  percent_complete: number | null;
  schedule_performance_index: number | null;
  severity: number;
}

export interface ProductivityAttention {
  as_of: string;
  pace_band_pct: number;
  total: number;
  items: AttentionRow[];
}

export interface AttentionParams {
  pace_band_pct?: number;
  resource_kind?: ResourceKind;
  status?: PhaseStatus;
  top_n?: number;
}

// ── Fetchers ─────────────────────────────────────────────────────────

export async function fetchProductivitySummary(
  params?: { pace_band_pct?: number },
): Promise<ProductivitySummary> {
  const { data } = await api.get<ProductivitySummary>(`${BASE}/summary`, {
    params,
  });
  return data;
}

export async function fetchProductivityAttention(
  params?: AttentionParams,
): Promise<ProductivityAttention> {
  const { data } = await api.get<ProductivityAttention>(`${BASE}/attention`, {
    params,
  });
  return data;
}

export async function fetchJobProductivityDetail(
  jobId: string,
  params?: { pace_band_pct?: number },
): Promise<JobProductivityDetail> {
  const path = encodeURIComponent(jobId);
  const { data } = await api.get<JobProductivityDetail>(
    `${BASE}/jobs/${path}`,
    { params },
  );
  return data;
}
