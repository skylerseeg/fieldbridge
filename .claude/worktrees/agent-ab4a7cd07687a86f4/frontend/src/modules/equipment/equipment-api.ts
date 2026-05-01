import { api } from "@/lib/api";

/**
 * Typed client for the FastAPI equipment module.
 *
 * Mirrors `backend/app/modules/equipment/schema.py` 1:1. Keep these in
 * sync — the backend is the source of truth, but TanStack Query needs
 * stable TS shapes, so any schema change there means an update here.
 *
 * Endpoint paths match the Vite dev proxy: `/api/...` resolves against
 * the dev server origin, which forwards to FastAPI on :8000. In prod,
 * `VITE_API_URL` prefixes everything (handled by the shared `api` axios
 * instance in `@/lib/api`).
 *
 * NOTE: The router uses the bare `/api/equipment` prefix (NOT
 * `/api/v1/equipment`) — see `app/main.py` where the `equipment` module
 * router is mounted directly. Be careful not to copy the v1 prefix from
 * other modules.
 */

const BASE = "/api/equipment";

// ── Enums ────────────────────────────────────────────────────────────

export type UtilizationBucket = "under" | "excessive" | "good" | "issues";
export type OwnershipKind = "owned" | "rented";
export type SortField =
  | "truck"
  | "tickets"
  | "total_qty"
  | "total_revenue"
  | "last_ticket_date";
export type SortDir = "asc" | "desc";

// ── Summary ──────────────────────────────────────────────────────────

export interface EquipmentSummary {
  total_assets: number;
  owned_assets: number;
  rented_assets: number;
  tickets_30d: number;
  revenue_30d: number;
  bucket_under: number;
  bucket_excessive: number;
  bucket_good: number;
  bucket_issues: number;
}

// ── List ─────────────────────────────────────────────────────────────

export interface EquipmentListRow {
  id: string;
  truck: string;
  ownership: OwnershipKind;
  tickets: number;
  total_qty: number;
  total_revenue: number;
  last_ticket_date: string | null;
  bucket: UtilizationBucket;
}

export interface EquipmentListResponse {
  total: number;
  page: number;
  page_size: number;
  sort_by: string;
  sort_dir: SortDir;
  items: EquipmentListRow[];
}

export interface ListParams {
  page?: number;
  page_size?: number;
  sort_by?: SortField;
  sort_dir?: SortDir;
  search?: string;
  bucket?: UtilizationBucket;
  ownership?: OwnershipKind;
}

// ── Status board ─────────────────────────────────────────────────────

export interface EquipmentCurrentJob {
  job_number: string | null;
  work_order: string | null;
  status: "open" | "hold" | "closed" | "unknown" | null;
  open_date: string | null;
  description: string | null;
}

export interface EquipmentLastTransfer {
  transfer_date: string | null;
  location: string | null;
  quantity: number | null;
  requested_by: string | null;
  user: string | null;
}

export interface EquipmentStatusRow {
  id: string;
  truck: string;
  bucket: UtilizationBucket;
  ownership: OwnershipKind;
  retired: boolean;
  retired_date: string | null;
  tickets: number;
  last_ticket_date: string | null;
  days_since_last_ticket: number | null;
  stale_ticket: boolean;
  current_job: EquipmentCurrentJob;
  last_transfer: EquipmentLastTransfer;
}

export interface EquipmentStatusResponse {
  as_of: string;
  stale_threshold_days: number;
  total: number;
  page: number;
  page_size: number;
  items: EquipmentStatusRow[];
}

export interface StatusParams {
  page?: number;
  page_size?: number;
  search?: string;
  bucket?: UtilizationBucket;
  stale_only?: boolean;
  include_retired?: boolean;
}

// ── Insights ─────────────────────────────────────────────────────────

export interface BucketBreakdown {
  under: number;
  excessive: number;
  good: number;
  issues: number;
}

export interface FuelCostPerHour {
  id: string;
  truck: string;
  hours: number;
  revenue: number;
  cost_per_hour: number;
}

export interface OwnershipMetrics {
  count: number;
  total_revenue: number;
  total_tickets: number;
  avg_tickets_per_asset: number;
}

export interface RentalMetrics {
  count: number;
  active_rentals: number;
  total_rate_committed: number;
  avg_rate: number;
}

export interface EquipmentInsights {
  as_of: string;
  utilization_buckets: BucketBreakdown;
  fuel_cost_per_hour_by_asset: FuelCostPerHour[];
  rental_vs_owned: {
    owned: OwnershipMetrics;
    rented: RentalMetrics;
  };
}

// ── Detail (used by future row drill-down) ───────────────────────────

export interface RecentTicket {
  ticket_date: string;
  ticket: string;
  job: string | null;
  material: string | null;
  qty: number | null;
  units: string | null;
  price: number | null;
  extended_price: number | null;
}

export interface EquipmentDetail {
  id: string;
  truck: string;
  ownership: OwnershipKind;
  bucket: UtilizationBucket;
  tickets: number;
  total_qty: number;
  total_revenue: number;
  first_ticket_date: string | null;
  last_ticket_date: string | null;
  cost_per_hour: number | null;
  manufacturer: string | null;
  model: string | null;
  material: string | null;
  retired_date: string | null;
  rental_company: string | null;
  picked_up_date: string | null;
  scheduled_return_date: string | null;
  returned_date: string | null;
  rental_rate: number | null;
  rate_unit: string | null;
  recent_tickets: RecentTicket[];
}

// ── Fetchers ─────────────────────────────────────────────────────────

export async function fetchEquipmentSummary(): Promise<EquipmentSummary> {
  const { data } = await api.get<EquipmentSummary>(`${BASE}/summary`);
  return data;
}

export async function fetchEquipmentList(
  params: ListParams,
): Promise<EquipmentListResponse> {
  const { data } = await api.get<EquipmentListResponse>(`${BASE}/list`, {
    params,
  });
  return data;
}

export async function fetchEquipmentStatus(
  params: StatusParams = {},
): Promise<EquipmentStatusResponse> {
  const { data } = await api.get<EquipmentStatusResponse>(`${BASE}/status`, {
    params,
  });
  return data;
}

export async function fetchEquipmentInsights(
  topN = 20,
): Promise<EquipmentInsights> {
  const { data } = await api.get<EquipmentInsights>(`${BASE}/insights`, {
    params: { top_n: topN },
  });
  return data;
}

export async function fetchEquipmentDetail(
  id: string,
): Promise<EquipmentDetail> {
  const { data } = await api.get<EquipmentDetail>(
    `${BASE}/${encodeURIComponent(id)}`,
  );
  return data;
}
