import { api } from "@/lib/api";

/**
 * Typed client for the FastAPI executive_dashboard module.
 *
 * Mirrors `backend/app/modules/executive_dashboard/schema.py` 1:1.
 * Backend is the source of truth — keep these in sync when the
 * Pydantic models there change.
 *
 * Mounted at the bare `/api/executive-dashboard` prefix in
 * `app/main.py` (NOT under `/api/v1`).
 */

const BASE = "/api/executive-dashboard";

// ── Enums ────────────────────────────────────────────────────────────

export type AttentionKind =
  | "loss"
  | "late"
  | "at_risk"
  | "over_billed"
  | "under_billed";

// ── Summary ──────────────────────────────────────────────────────────

export interface FinancialPulse {
  active_jobs: number;
  total_contract_value: number;
  total_revenue_earned: number;
  total_cost_to_date: number;
  total_estimated_gross_profit: number;
  /** Fractional: 0.115 = 11.5%. */
  weighted_gross_profit_pct: number;
  total_over_under_billings: number;
  over_billed_jobs: number;
  under_billed_jobs: number;
  balanced_jobs: number;
}

export interface OperationsPulse {
  scheduled_jobs: number;
  jobs_at_risk: number;
  jobs_late: number;
  total_equipment: number;
  equipment_tickets_30d: number;
  equipment_revenue_30d: number;
}

export interface PipelinePulse {
  bids_in_pipeline: number;
  bids_ready_for_review: number;
  upcoming_bids_30d: number;
  bids_submitted_ytd: number;
  bids_won_ytd: number;
  /** Fractional: 0.42 = 42%. */
  win_rate_ytd: number;
  proposals_outstanding: number;
}

export interface RosterPulse {
  total_vendors: number;
  total_assets: number;
  retired_assets: number;
}

export interface ExecutiveSummary {
  as_of: string;
  financial: FinancialPulse;
  operations: OperationsPulse;
  pipeline: PipelinePulse;
  roster: RosterPulse;
}

// ── Attention ───────────────────────────────────────────────────────

export interface AttentionItem {
  job_id: string;
  job: string;
  kind: AttentionKind;
  /** Backend rank fuel — larger = worse. */
  severity: number;
  detail: string;
  total_contract: number | null;
  est_gross_profit_pct: number | null;
  over_under_billings: number | null;
  days_to_proj_end: number | null;
}

export interface ExecutiveAttention {
  as_of: string;
  items: AttentionItem[];
}

// ── Trend ────────────────────────────────────────────────────────────

export interface MonthlyRevenuePoint {
  /** "YYYY-MM". */
  month: string;
  estimate: number;
  actual: number;
}

export interface ExecutiveTrend {
  as_of: string;
  months: MonthlyRevenuePoint[];
}

// ── Fetchers ─────────────────────────────────────────────────────────

export async function fetchExecutiveSummary(): Promise<ExecutiveSummary> {
  const { data } = await api.get<ExecutiveSummary>(`${BASE}/summary`);
  return data;
}

export async function fetchExecutiveAttention(
  topN = 10,
): Promise<ExecutiveAttention> {
  const { data } = await api.get<ExecutiveAttention>(`${BASE}/attention`, {
    params: { top_n: topN },
  });
  return data;
}

export async function fetchExecutiveTrend(
  months = 12,
): Promise<ExecutiveTrend> {
  const { data } = await api.get<ExecutiveTrend>(`${BASE}/trend`, {
    params: { months },
  });
  return data;
}
