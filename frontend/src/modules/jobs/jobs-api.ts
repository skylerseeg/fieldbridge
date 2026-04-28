import { api } from "@/lib/api";

/**
 * Typed client for the FastAPI jobs module.
 *
 * Mirrors `backend/app/modules/jobs/schema.py` 1:1. Jobs is the first
 * mart with real P&L flow — three orthogonal status axes (schedule,
 * financial, billing), plus aggregate estimate accuracy and top-N money
 * lists.
 *
 * Mounted at `/api/jobs` (NOT `/api/v1/jobs`) — see `app/main.py`.
 */

const BASE = "/api/jobs";

// ── Enums ────────────────────────────────────────────────────────────

export type ScheduleStatus =
  | "on_schedule"
  | "at_risk"
  | "late"
  | "no_schedule"
  | "unknown";

export type FinancialStatus =
  | "profitable"
  | "breakeven"
  | "loss"
  | "unknown";

export type BillingStatus =
  | "over_billed"
  | "balanced"
  | "under_billed"
  | "unknown";

export type SortField =
  | "job"
  | "priority"
  | "proj_end"
  | "percent_complete"
  | "total_contract"
  | "contract_cost_td"
  | "est_gross_profit"
  | "est_gross_profit_pct"
  | "gross_profit_pct_td"
  | "over_under_billings"
  | "schedule_days_to_end";

export type SortDir = "asc" | "desc";

// ── List ─────────────────────────────────────────────────────────────

export interface JobListRow {
  id: string;
  job: string;

  priority: number | null;
  start: string | null;
  proj_end: string | null;
  milestone: string | null;
  schedule_days_to_end: number | null;
  schedule_status: ScheduleStatus;

  total_contract: number | null;
  contract_cost_td: number | null;
  est_total_cost: number | null;
  est_gross_profit: number | null;
  est_gross_profit_pct: number | null;
  gross_profit_pct_td: number | null;
  percent_complete: number | null;
  billings_to_date: number | null;
  over_under_billings: number | null;

  financial_status: FinancialStatus;
  billing_status: BillingStatus;
}

export interface JobListResponse {
  total: number;
  page: number;
  page_size: number;
  sort_by: string;
  sort_dir: SortDir;
  items: JobListRow[];
}

export interface ListParams {
  page?: number;
  page_size?: number;
  sort_by?: SortField;
  sort_dir?: SortDir;
  schedule_status?: ScheduleStatus;
  financial_status?: FinancialStatus;
  billing_status?: BillingStatus;
  search?: string;
}

// ── Summary ──────────────────────────────────────────────────────────

export interface JobSummary {
  total_jobs: number;
  jobs_with_wip: number;
  jobs_scheduled: number;

  total_contract_value: number;
  total_cost_to_date: number;
  total_revenue_earned: number;
  total_gross_profit_td: number;

  weighted_avg_margin_pct: number | null;
  avg_percent_complete: number;

  jobs_on_schedule: number;
  jobs_at_risk: number;
  jobs_late: number;

  jobs_profitable: number;
  jobs_breakeven: number;
  jobs_loss: number;

  jobs_over_billed: number;
  jobs_under_billed: number;
  jobs_balanced: number;
}

// ── Insights ─────────────────────────────────────────────────────────

export interface ScheduleBreakdown {
  on_schedule: number;
  at_risk: number;
  late: number;
  no_schedule: number;
  unknown: number;
}

export interface FinancialBreakdown {
  profitable: number;
  breakeven: number;
  loss: number;
  unknown: number;
}

export interface BillingMetrics {
  over_billed_count: number;
  balanced_count: number;
  under_billed_count: number;
  unknown_count: number;
  total_over_billed: number;
  total_under_billed: number;
}

export interface EstimateAccuracy {
  samples: number;
  jobs_tracked: number;
  avg_variance_pct: number | null;
  avg_abs_variance_pct: number | null;
}

export interface JobMoneyRow {
  id: string;
  job: string;
  value: number;
  percent_complete: number | null;
  total_contract: number | null;
}

export interface JobsInsights {
  as_of: string;
  at_risk_days: number;
  breakeven_band_pct: number;
  billing_balance_pct: number;
  schedule_breakdown: ScheduleBreakdown;
  financial_breakdown: FinancialBreakdown;
  billing_metrics: BillingMetrics;
  estimate_accuracy: EstimateAccuracy;
  top_profit: JobMoneyRow[];
  top_loss: JobMoneyRow[];
  top_over_billed: JobMoneyRow[];
  top_under_billed: JobMoneyRow[];
}

// ── Detail (used by future row drill-down) ───────────────────────────

export interface EstimateHistoryPoint {
  close_month: string;
  estimate: number | null;
  actual: number | null;
  variance: number | null;
  variance_pct: number | null;
}

export interface JobDetail {
  id: string;
  job: string;
  priority: number | null;
  start: string | null;
  proj_end: string | null;
  milestone: string | null;
  schedule_days_to_end: number | null;
  schedule_status: ScheduleStatus;
  reason: string | null;
  total_contract: number | null;
  contract_cost_td: number | null;
  est_cost_to_complete: number | null;
  est_total_cost: number | null;
  est_gross_profit: number | null;
  est_gross_profit_pct: number | null;
  percent_complete: number | null;
  gain_fade_from_prior_mth: number | null;
  billings_to_date: number | null;
  over_under_billings: number | null;
  contract_revenues_earned: number | null;
  gross_profit_loss_td: number | null;
  gross_profit_pct_td: number | null;
  financial_status: FinancialStatus;
  billing_status: BillingStatus;
  estimate_history: EstimateHistoryPoint[];
}

// ── Fetchers ─────────────────────────────────────────────────────────

export async function fetchJobSummary(): Promise<JobSummary> {
  const { data } = await api.get<JobSummary>(`${BASE}/summary`);
  return data;
}

export async function fetchJobList(
  params: ListParams,
): Promise<JobListResponse> {
  const { data } = await api.get<JobListResponse>(`${BASE}/list`, { params });
  return data;
}

export async function fetchJobInsights(topN = 10): Promise<JobsInsights> {
  const { data } = await api.get<JobsInsights>(`${BASE}/insights`, {
    params: { top_n: topN },
  });
  return data;
}

export async function fetchJobDetail(id: string): Promise<JobDetail> {
  const { data } = await api.get<JobDetail>(
    `${BASE}/${encodeURIComponent(id)}`,
  );
  return data;
}
