import { api } from "@/lib/api";

/**
 * Typed client for the FastAPI timecards module.
 *
 * Mirrors `backend/app/modules/timecards/schema.py` 1:1. Each row is a
 * job class (`class_name`) — a join of `mart_fte_class_actual` (rolling
 * 12-month FTE counts) with `mart_fte_class_projected` (planned FTE).
 *
 * Two angles surface here:
 *   - **Variance** — actual vs projected FTE, classified into ±band%
 *     (`under` / `on_track` / `over` / `unknown`).
 *   - **Overtime**  — last-month actuals minus monthly target hours.
 *
 * Plus the **overhead ratio** — overhead-department FTE divided by
 * total (overhead + direct labor).
 *
 * Mounted at `/api/timecards` (NOT `/api/v1/timecards`) — see
 * `app/main.py`.
 */

const BASE = "/api/timecards";

// ── Enums ────────────────────────────────────────────────────────────

export type VarianceStatus = "under" | "on_track" | "over" | "unknown";

export type SortField =
  | "class_name"
  | "actual_avg_fte"
  | "projected_avg_fte"
  | "variance"
  | "variance_pct"
  | "overtime_pct"
  | "monthly_hours"
  | "last_month_actuals";

export type SortDir = "asc" | "desc";

// ── List ─────────────────────────────────────────────────────────────

export interface TimecardListRow {
  id: string;
  class_name: string;
  code: string | null;
  craft_class: string | null;

  monthly_hours: number | null;
  last_month_actuals: number | null;

  actual_avg_fte: number | null;
  projected_avg_fte: number | null;
  variance: number | null;
  variance_pct: number | null;
  variance_status: VarianceStatus;

  overtime_hours: number | null;
  overtime_pct: number | null;
}

export interface TimecardListResponse {
  total: number;
  page: number;
  page_size: number;
  sort_by: string;
  sort_dir: SortDir;
  items: TimecardListRow[];
}

export interface ListParams {
  page?: number;
  page_size?: number;
  sort_by?: SortField;
  sort_dir?: SortDir;
  status?: VarianceStatus;
  search?: string;
  overtime_only?: boolean;
  band_pct?: number;
}

// ── Summary ──────────────────────────────────────────────────────────

export interface TimecardSummary {
  total_classes: number;
  total_overhead_departments: number;
  total_job_types: number;

  total_actual_fte: number;
  total_projected_fte: number;
  total_variance_pct: number | null;

  avg_overtime_pct: number;
  classes_with_overtime: number;

  overhead_ratio_pct: number | null;
}

// ── Insights ─────────────────────────────────────────────────────────

export interface VarianceByClass {
  class_name: string;
  actual_avg_fte: number | null;
  projected_avg_fte: number | null;
  variance: number | null;
  variance_pct: number | null;
  variance_status: VarianceStatus;
}

export interface OvertimeByClass {
  class_name: string;
  monthly_hours: number | null;
  last_month_actuals: number | null;
  overtime_hours: number | null;
  overtime_pct: number | null;
}

export interface OverheadRatio {
  overhead_fte: number;
  direct_fte: number;
  ratio_pct: number | null;
}

export interface TimecardInsights {
  as_of: string;
  variance_band_pct: number;
  variance_over: VarianceByClass[];
  variance_under: VarianceByClass[];
  overtime_leaders: OvertimeByClass[];
  overhead_ratio: OverheadRatio;
}

// ── Detail (used by future row drill-down) ───────────────────────────

export interface MonthlyPoint {
  month: string;
  actual: number | null;
  projected: number | null;
}

export interface TimecardDetail {
  id: string;
  class_name: string;
  code: string | null;
  craft_class: string | null;

  monthly_hours: number | null;
  last_month_actuals: number | null;

  actual_avg_fte: number | null;
  projected_avg_fte: number | null;
  variance: number | null;
  variance_pct: number | null;
  variance_status: VarianceStatus;

  overtime_hours: number | null;
  overtime_pct: number | null;

  monthly_breakdown: MonthlyPoint[];
}

// ── Fetchers ─────────────────────────────────────────────────────────

export async function fetchTimecardSummary(): Promise<TimecardSummary> {
  const { data } = await api.get<TimecardSummary>(`${BASE}/summary`);
  return data;
}

export async function fetchTimecardList(
  params: ListParams,
): Promise<TimecardListResponse> {
  const { data } = await api.get<TimecardListResponse>(`${BASE}/list`, {
    params,
  });
  return data;
}

export async function fetchTimecardInsights(
  topN = 10,
): Promise<TimecardInsights> {
  const { data } = await api.get<TimecardInsights>(`${BASE}/insights`, {
    params: { top_n: topN },
  });
  return data;
}

export async function fetchTimecardDetail(
  className: string,
): Promise<TimecardDetail> {
  const { data } = await api.get<TimecardDetail>(
    `${BASE}/${encodeURIComponent(className)}`,
  );
  return data;
}
