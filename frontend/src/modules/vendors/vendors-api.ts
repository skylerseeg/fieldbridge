import { api } from "@/lib/api";

/**
 * Typed client for the FastAPI vendors module.
 *
 * Mirrors `backend/app/modules/vendors/schema.py` 1:1. Vendors is a
 * directory-health mart (no transaction $ flow) so the metrics here are
 * data-completeness oriented: contact tiers, CSI coding coverage,
 * firm-type mix.
 *
 * Mounted at `/api/vendors` (NOT `/api/v1/vendors`) — see `app/main.py`.
 */

const BASE = "/api/vendors";

// ── Enums ────────────────────────────────────────────────────────────

export type FirmType =
  | "supplier"
  | "contractor"
  | "service"
  | "internal"
  | "unknown";

export type ContactStatus = "complete" | "partial" | "minimal" | "empty";
export type CodingStatus = "coded" | "uncoded";

export type SortField =
  | "name"
  | "firm_type"
  | "code_count"
  | "primary_division";
export type SortDir = "asc" | "desc";

// ── List ─────────────────────────────────────────────────────────────

export interface VendorListRow {
  id: string;
  name: string | null;
  firm_type: FirmType;
  firm_type_raw: string | null;
  contact: string | null;
  title: string | null;
  email: string | null;
  phone: string | null;
  codes: string[];
  code_count: number;
  primary_division: string | null;
  contact_status: ContactStatus;
  coding_status: CodingStatus;
  enriched: boolean;
  enriched_at: string | null;
}

export interface VendorListResponse {
  total: number;
  page: number;
  page_size: number;
  sort_by: string;
  sort_dir: SortDir;
  items: VendorListRow[];
}

export interface ListParams {
  page?: number;
  page_size?: number;
  sort_by?: SortField;
  sort_dir?: SortDir;
  firm_type?: FirmType;
  contact_status?: ContactStatus;
  coding_status?: CodingStatus;
  division?: string;
  search?: string;
}

// ── Summary ──────────────────────────────────────────────────────────

export interface VendorSummary {
  total_vendors: number;
  with_name: number;
  with_contact: number;
  with_email: number;
  with_phone: number;
  complete_contact: number;
  coded_vendors: number;
  uncoded_vendors: number;
  distinct_codes: number;
  distinct_divisions: number;
  suppliers: number;
  contractors: number;
  services: number;
  internal: number;
  unknown_firm_type: number;
}

// ── Insights ─────────────────────────────────────────────────────────

export interface FirmTypeBreakdown {
  supplier: number;
  contractor: number;
  service: number;
  internal: number;
  unknown: number;
}

export interface ContactHealthBreakdown {
  complete: number;
  partial: number;
  minimal: number;
  empty: number;
}

export interface CodingBreakdown {
  coded: number;
  uncoded: number;
}

export interface DivisionMixRow {
  division: string;
  vendor_count: number;
  code_count: number;
  example_code: string | null;
}

export interface CodeMixRow {
  code: string;
  vendor_count: number;
  top_firm_type: FirmType;
}

export interface VendorDepthRow {
  id: string;
  name: string | null;
  code_count: number;
  codes: string[];
  firm_type: FirmType;
}

export interface VendorsInsights {
  firm_type_breakdown: FirmTypeBreakdown;
  contact_health: ContactHealthBreakdown;
  coding_breakdown: CodingBreakdown;
  top_codes: CodeMixRow[];
  top_divisions: DivisionMixRow[];
  thin_divisions: DivisionMixRow[];
  depth_leaders: VendorDepthRow[];
}

// ── Detail (used by future row drill-down) ───────────────────────────

export interface VendorDetail {
  id: string;
  name: string | null;
  firm_type: FirmType;
  firm_type_raw: string | null;
  contact: string | null;
  title: string | null;
  email: string | null;
  phone: string | null;
  codes: string[];
  code_count: number;
  primary_division: string | null;
  divisions: string[];
  contact_status: ContactStatus;
  coding_status: CodingStatus;
  enriched: boolean;
  enriched_at: string | null;
  enrichment_notes: string | null;
}

export interface VendorEnrichmentPayload {
  contact?: string | null;
  title?: string | null;
  email?: string | null;
  phone?: string | null;
  firm_type?: FirmType | null;
  codes?: string[];
  notes?: string | null;
}

// ── Fetchers ─────────────────────────────────────────────────────────

export async function fetchVendorSummary(): Promise<VendorSummary> {
  const { data } = await api.get<VendorSummary>(`${BASE}/summary`);
  return data;
}

export async function fetchVendorList(
  params: ListParams,
): Promise<VendorListResponse> {
  const { data } = await api.get<VendorListResponse>(`${BASE}/list`, {
    params,
  });
  return data;
}

export async function fetchVendorInsights(
  topN = 10,
  thinDivisionMax = 2,
): Promise<VendorsInsights> {
  const { data } = await api.get<VendorsInsights>(`${BASE}/insights`, {
    params: { top_n: topN, thin_division_max: thinDivisionMax },
  });
  return data;
}

export async function fetchVendorDetail(id: string): Promise<VendorDetail> {
  const { data } = await api.get<VendorDetail>(
    `${BASE}/${encodeURIComponent(id)}`,
  );
  return data;
}

export async function enrichVendor(
  id: string,
  payload: VendorEnrichmentPayload,
): Promise<VendorDetail> {
  const { data } = await api.post<VendorDetail>(
    `${BASE}/enrichments/${encodeURIComponent(id)}`,
    payload,
  );
  return data;
}
