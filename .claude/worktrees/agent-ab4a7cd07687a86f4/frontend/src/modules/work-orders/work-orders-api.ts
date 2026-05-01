import { api } from "@/lib/api";

/**
 * Typed client for the FastAPI work-orders module.
 *
 * Mirrors `backend/app/modules/work_orders/schema.py` 1:1. Each row is
 * an `emwo` record (Vista equipment work order) keyed by WO number.
 * Vista status codes (`O` / `C` / `H`) and priority codes (`1` / `2` /
 * `3`) are normalized server-side into friendly enum strings before
 * they reach this client.
 *
 * Mounted at `/api/work-orders` (NOT `/api/v1/work-orders`) — see
 * `app/main.py`. Note the hyphen in the URL even though the Python
 * package uses an underscore.
 */

const BASE = "/api/work-orders";

// ── Enums ────────────────────────────────────────────────────────────

export type WorkOrderStatus = "open" | "closed" | "hold" | "unknown";

export type WorkOrderPriority =
  | "critical"
  | "high"
  | "normal"
  | "unknown";

export type SortField =
  | "work_order"
  | "equipment"
  | "status"
  | "priority"
  | "open_date"
  | "closed_date"
  | "age_days"
  | "total_cost";

export type SortDir = "asc" | "desc";

// ── List ─────────────────────────────────────────────────────────────

export interface WorkOrderListRow {
  id: string;
  work_order: string;
  equipment: string | null;
  description: string | null;
  status: WorkOrderStatus;
  priority: WorkOrderPriority;
  open_date: string | null;
  closed_date: string | null;
  age_days: number | null;
  overdue: boolean;
  mechanic: string | null;
  total_cost: number | null;
  estimated_cost: number | null;
}

export interface WorkOrderListResponse {
  total: number;
  page: number;
  page_size: number;
  sort_by: string;
  sort_dir: SortDir;
  items: WorkOrderListRow[];
}

export interface ListParams {
  page?: number;
  page_size?: number;
  sort_by?: SortField;
  sort_dir?: SortDir;
  status?: WorkOrderStatus;
  priority?: WorkOrderPriority;
  equipment?: string;
  mechanic?: string;
  overdue?: boolean;
  search?: string;
  overdue_days?: number;
}

// ── Summary ──────────────────────────────────────────────────────────

export interface WorkOrderSummary {
  total_work_orders: number;
  open_count: number;
  closed_count: number;
  hold_count: number;
  overdue_count: number;
  overdue_threshold_days: number;
  avg_age_days_open: number;
  total_cost_to_date: number;
  total_budget: number;
}

// ── Insights ─────────────────────────────────────────────────────────

export interface StatusCounts {
  open: number;
  closed: number;
  hold: number;
  unknown: number;
}

export interface CostVsBudget {
  cost_to_date: number;
  budget: number;
  variance: number;
  variance_pct: number | null;
}

export interface WorkOrderInsights {
  as_of: string;
  overdue_threshold_days: number;
  status_counts: StatusCounts;
  avg_age_days_open: number;
  overdue_count: number;
  cost_vs_budget: CostVsBudget;
}

// ── Detail (used by future row drill-down) ───────────────────────────

export interface WorkOrderDetail {
  id: string;
  work_order: string;
  equipment: string | null;
  description: string | null;
  status: WorkOrderStatus;
  priority: WorkOrderPriority;
  requested_by: string | null;
  mechanic: string | null;
  job_number: string | null;
  open_date: string | null;
  closed_date: string | null;
  age_days: number | null;
  overdue: boolean;
  labor_hours: number | null;
  estimated_hours: number | null;
  parts_cost: number | null;
  total_cost: number | null;
  estimated_cost: number | null;
  cost_variance: number | null;
  cost_variance_pct: number | null;
}

// ── Fetchers ─────────────────────────────────────────────────────────

export async function fetchWorkOrderSummary(): Promise<WorkOrderSummary> {
  const { data } = await api.get<WorkOrderSummary>(`${BASE}/summary`);
  return data;
}

export async function fetchWorkOrderList(
  params: ListParams,
): Promise<WorkOrderListResponse> {
  const { data } = await api.get<WorkOrderListResponse>(`${BASE}/list`, {
    params,
  });
  return data;
}

export async function fetchWorkOrderInsights(): Promise<WorkOrderInsights> {
  const { data } = await api.get<WorkOrderInsights>(`${BASE}/insights`);
  return data;
}

export async function fetchWorkOrderDetail(
  workOrder: string,
): Promise<WorkOrderDetail> {
  const { data } = await api.get<WorkOrderDetail>(
    `${BASE}/${encodeURIComponent(workOrder)}`,
  );
  return data;
}
