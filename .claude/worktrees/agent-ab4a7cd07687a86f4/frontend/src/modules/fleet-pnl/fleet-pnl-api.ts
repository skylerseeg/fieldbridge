import { api } from "@/lib/api";

/**
 * Typed client for the FastAPI fleet_pnl module.
 *
 * Mirrors `backend/app/modules/fleet_pnl/schema.py` 1:1. The primary
 * entity is a **truck** (VanCon's trucks are keyed by tag — e.g.
 * `TK149`). Each row rolls up haul-ticket activity from
 * `mart_equipment_utilization` (revenue, qty, invoicing, breadth) plus
 * three orthogonal classifications:
 *   - `lessor_flag`     — owned / lessor / mixed / unknown
 *   - `invoice_bucket`  — fully / partially / uninvoiced / unknown
 *   - `utilization_bucket` — idle / underutilized / healthy / heavy
 *
 * Rental-IN cost (rented FROM external vendors) lives separately on the
 * summary + insights endpoints since it can't be keyed by truck tag.
 *
 * Mounted at `/api/fleet-pnl` (NOT `/api/v1/fleet-pnl`) — see
 * `app/main.py`. Note the hyphen in the URL even though the Python
 * package uses an underscore.
 */

const BASE = "/api/fleet-pnl";

// ── Enums ────────────────────────────────────────────────────────────

export type LessorFlag = "owned" | "lessor" | "mixed" | "unknown";

export type InvoiceBucket =
  | "fully_invoiced"
  | "partially_invoiced"
  | "uninvoiced"
  | "unknown";

export type UtilizationBucket =
  | "idle"
  | "underutilized"
  | "healthy"
  | "heavily_utilized";

export type SortField =
  | "truck"
  | "ticket_count"
  | "revenue"
  | "uninvoiced_revenue"
  | "invoiced_revenue"
  | "total_qty"
  | "invoice_rate"
  | "jobs_served"
  | "vendors_served"
  | "last_ticket";

export type SortDir = "asc" | "desc";

// ── List ─────────────────────────────────────────────────────────────

export interface TruckListRow {
  id: string;
  truck: string;

  ticket_count: number;
  total_qty: number;
  revenue: number;
  avg_price_per_ticket: number | null;

  invoiced_count: number;
  invoiced_revenue: number;
  uninvoiced_revenue: number;
  invoice_rate: number | null;

  jobs_served: number;
  vendors_served: number;

  first_ticket: string | null;
  last_ticket: string | null;
  active_days: number | null;

  lessor_flag: LessorFlag;
  invoice_bucket: InvoiceBucket;
  utilization_bucket: UtilizationBucket;

  top_material: string | null;
  top_vendor: string | null;
  top_job: string | null;
  top_driver: string | null;
}

export interface TruckListResponse {
  total: number;
  page: number;
  page_size: number;
  sort_by: string;
  sort_dir: SortDir;
  items: TruckListRow[];
}

export interface ListParams {
  page?: number;
  page_size?: number;
  sort_by?: SortField;
  sort_dir?: SortDir;
  lessor_flag?: LessorFlag;
  invoice_bucket?: InvoiceBucket;
  utilization_bucket?: UtilizationBucket;
  search?: string;
  underutilized_max_tickets?: number;
  heavily_utilized_min_tickets?: number;
}

// ── Summary ──────────────────────────────────────────────────────────

export interface FleetSummary {
  total_trucks: number;
  total_tickets: number;
  total_qty: number;
  total_revenue: number;

  invoiced_revenue: number;
  uninvoiced_revenue: number;
  invoice_rate: number | null;

  owned_trucks: number;
  lessor_trucks: number;
  mixed_trucks: number;
  unknown_ownership_trucks: number;

  first_ticket: string | null;
  last_ticket: string | null;
  active_days: number | null;

  unique_jobs: number;
  unique_vendors: number;
  unique_drivers: number;

  rental_contracts: number;
  rental_monthly_cost: number;
}

// ── Insights ─────────────────────────────────────────────────────────

export interface UtilizationBreakdown {
  idle: number;
  underutilized: number;
  healthy: number;
  heavily_utilized: number;
}

export interface InvoiceBreakdown {
  fully_invoiced: number;
  partially_invoiced: number;
  uninvoiced: number;
  unknown: number;
}

export interface FleetMixRow {
  label: string;
  ticket_count: number;
  revenue: number;
  qty: number;
}

export interface RentalInSummary {
  contracts: number;
  active_contracts: number;
  rpo_contracts: number;
  total_monthly_cost: number;
  total_hourly_cost: number;
  top_rental_vendors: FleetMixRow[];
}

export interface TruckMoneyRow {
  id: string;
  truck: string;
  value: number;
  ticket_count: number | null;
  revenue: number | null;
}

export interface FleetPnlInsights {
  as_of: string;
  underutilized_max_tickets: number;
  heavily_utilized_min_tickets: number;

  utilization_breakdown: UtilizationBreakdown;
  invoice_breakdown: InvoiceBreakdown;
  rental_in: RentalInSummary;

  top_revenue: TruckMoneyRow[];
  top_uninvoiced: TruckMoneyRow[];
  top_underutilized: TruckMoneyRow[];
  top_vendors: FleetMixRow[];
  top_materials: FleetMixRow[];
  top_jobs: FleetMixRow[];
}

// ── Detail (used by future row drill-down) ───────────────────────────

export interface FleetTicketPoint {
  ticket: string | null;
  ticket_date: string | null;
  job: string | null;
  vendor: string | null;
  pit: string | null;
  material: string | null;
  driver: string | null;
  qty: number | null;
  units: string | null;
  price: number | null;
  extended_price: number | null;
  invoiced: boolean | null;
  invoice_number: string | null;
}

export interface FleetMonthlyPoint {
  month: string;
  ticket_count: number;
  revenue: number;
  qty: number;
}

export interface FleetTruckDetail {
  id: string;
  truck: string;

  ticket_count: number;
  total_qty: number;
  revenue: number;
  avg_price_per_ticket: number | null;

  invoiced_count: number;
  invoiced_revenue: number;
  uninvoiced_revenue: number;
  invoice_rate: number | null;

  jobs_served: number;
  vendors_served: number;

  first_ticket: string | null;
  last_ticket: string | null;
  active_days: number | null;

  lessor_flag: LessorFlag;
  invoice_bucket: InvoiceBucket;
  utilization_bucket: UtilizationBucket;

  top_material: string | null;
  top_vendor: string | null;
  top_job: string | null;
  top_driver: string | null;

  recent_tickets: FleetTicketPoint[];
  monthly_series: FleetMonthlyPoint[];
  vendor_mix: FleetMixRow[];
  material_mix: FleetMixRow[];
  job_mix: FleetMixRow[];
  driver_mix: FleetMixRow[];
}

// ── Fetchers ─────────────────────────────────────────────────────────

export async function fetchFleetSummary(): Promise<FleetSummary> {
  const { data } = await api.get<FleetSummary>(`${BASE}/summary`);
  return data;
}

export async function fetchFleetList(
  params: ListParams,
): Promise<TruckListResponse> {
  const { data } = await api.get<TruckListResponse>(`${BASE}/list`, {
    params,
  });
  return data;
}

export async function fetchFleetInsights(
  topN = 10,
): Promise<FleetPnlInsights> {
  const { data } = await api.get<FleetPnlInsights>(`${BASE}/insights`, {
    params: { top_n: topN },
  });
  return data;
}

export async function fetchFleetTruckDetail(
  id: string,
): Promise<FleetTruckDetail> {
  const { data } = await api.get<FleetTruckDetail>(
    `${BASE}/${encodeURIComponent(id)}`,
  );
  return data;
}
