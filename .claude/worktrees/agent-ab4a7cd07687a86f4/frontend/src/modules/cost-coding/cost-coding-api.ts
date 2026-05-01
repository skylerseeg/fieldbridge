import { api } from "@/lib/api";

/**
 * Typed client for the FastAPI cost_coding module.
 *
 * Mirrors `backend/app/modules/cost_coding/schema.py` 1:1. Each row is
 * a **cost code** (HCSS `activity_code`) rolled up across every
 * estimate it appears in.
 *
 * Three orthogonal classifications per code:
 *   - **CostCategory** — which bucket dominates spend (labor /
 *     permanent_material / construction_material / equipment /
 *     subcontract / mixed / zero).
 *   - **CostSizeTier** — total-dollar magnitude (major / significant /
 *     minor / zero).
 *   - **UsageTier** — how many distinct estimates reference the code
 *     (heavy / regular / light / singleton).
 *
 * Mounted at `/api/cost-coding` (NOT `/api/v1/cost-coding`) — see
 * `app/main.py`. Note the hyphen in the URL even though the Python
 * package uses an underscore.
 */

const BASE = "/api/cost-coding";

// ── Enums ────────────────────────────────────────────────────────────

export type CostCategory =
  | "labor"
  | "permanent_material"
  | "construction_material"
  | "equipment"
  | "subcontract"
  | "mixed"
  | "zero";

export type CostSizeTier = "major" | "significant" | "minor" | "zero";

export type UsageTier = "heavy" | "regular" | "light" | "singleton";

export type SortField =
  | "code"
  | "estimate_count"
  | "total_direct_cost"
  | "total_man_hours"
  | "labor_cost"
  | "equipment_cost"
  | "subcontract_cost";

export type SortDir = "asc" | "desc";

// ── List ─────────────────────────────────────────────────────────────

export interface CostCodeListRow {
  id: string;
  code: string;
  description: string | null;
  major_code: string | null;

  estimate_count: number;
  total_man_hours: number;
  total_direct_cost: number;

  labor_cost: number;
  permanent_material_cost: number;
  construction_material_cost: number;
  equipment_cost: number;
  subcontract_cost: number;

  cost_category: CostCategory;
  size_tier: CostSizeTier;
  usage_tier: UsageTier;
}

export interface CostCodeListResponse {
  total: number;
  page: number;
  page_size: number;
  sort_by: string;
  sort_dir: SortDir;
  items: CostCodeListRow[];
}

export interface ListParams {
  page?: number;
  page_size?: number;
  sort_by?: SortField;
  sort_dir?: SortDir;
  cost_category?: CostCategory;
  size_tier?: CostSizeTier;
  usage_tier?: UsageTier;
  major_code?: string;
  search?: string;
  category_dominance?: number;
  major_cost_min?: number;
  significant_cost_min?: number;
  heavy_min?: number;
  regular_min?: number;
}

// ── Summary ──────────────────────────────────────────────────────────

export interface CostCodingSummary {
  total_codes: number;
  total_activities: number;
  distinct_estimates: number;

  total_man_hours: number;
  total_direct_cost: number;
  total_labor_cost: number;
  total_permanent_material_cost: number;
  total_construction_material_cost: number;
  total_equipment_cost: number;
  total_subcontract_cost: number;

  codes_with_labor: number;
  codes_with_permanent_material: number;
  codes_with_construction_material: number;
  codes_with_equipment: number;
  codes_with_subcontract: number;

  uncosted_codes: number;
}

// ── Insights ─────────────────────────────────────────────────────────

export interface CostCategoryBreakdown {
  labor: number;
  permanent_material: number;
  construction_material: number;
  equipment: number;
  subcontract: number;
  mixed: number;
  zero: number;
}

export interface SizeTierBreakdown {
  major: number;
  significant: number;
  minor: number;
  zero: number;
}

export interface UsageTierBreakdown {
  heavy: number;
  regular: number;
  light: number;
  singleton: number;
}

export interface CostCategoryMixRow {
  category: CostCategory;
  code_count: number;
  total_direct_cost: number;
  share_of_total: number;
}

export interface MajorCodeRollup {
  major_code: string;
  code_count: number;
  estimate_count: number;
  total_direct_cost: number;
  total_man_hours: number;
  example_description: string | null;
}

export interface TopCostCodeRow {
  code: string;
  description: string | null;
  estimate_count: number;
  total_direct_cost: number;
  total_man_hours: number;
  cost_category: CostCategory;
}

export interface CostCodingInsights {
  category_breakdown: CostCategoryBreakdown;
  size_tier_breakdown: SizeTierBreakdown;
  usage_tier_breakdown: UsageTierBreakdown;
  category_mix: CostCategoryMixRow[];
  top_by_cost: TopCostCodeRow[];
  top_by_usage: TopCostCodeRow[];
  top_by_hours: TopCostCodeRow[];
  top_major_codes: MajorCodeRollup[];
  uncosted_codes: TopCostCodeRow[];
}

// ── Detail (used by future row drill-down) ───────────────────────────

export interface CostCodeEstimateBreakdown {
  estimate_code: string;
  estimate_name: string | null;
  activity_description: string | null;
  man_hours: number;
  direct_total_cost: number;
  labor_cost: number;
  permanent_material_cost: number;
  construction_material_cost: number;
  equipment_cost: number;
  subcontract_cost: number;
}

export interface CostCodeDetail {
  id: string;
  code: string;
  description: string | null;
  major_code: string | null;

  estimate_count: number;
  total_man_hours: number;
  total_direct_cost: number;

  labor_cost: number;
  permanent_material_cost: number;
  construction_material_cost: number;
  equipment_cost: number;
  subcontract_cost: number;

  cost_category: CostCategory;
  size_tier: CostSizeTier;
  usage_tier: UsageTier;

  distinct_descriptions: number;
  estimates: CostCodeEstimateBreakdown[];
}

// ── Fetchers ─────────────────────────────────────────────────────────

export async function fetchCostCodingSummary(): Promise<CostCodingSummary> {
  const { data } = await api.get<CostCodingSummary>(`${BASE}/summary`);
  return data;
}

export async function fetchCostCodingList(
  params: ListParams,
): Promise<CostCodeListResponse> {
  const { data } = await api.get<CostCodeListResponse>(`${BASE}/list`, {
    params,
  });
  return data;
}

export async function fetchCostCodingInsights(
  topN = 10,
): Promise<CostCodingInsights> {
  const { data } = await api.get<CostCodingInsights>(`${BASE}/insights`, {
    params: { top_n: topN },
  });
  return data;
}

export async function fetchCostCodeDetail(
  codeId: string,
): Promise<CostCodeDetail> {
  const { data } = await api.get<CostCodeDetail>(
    `${BASE}/${encodeURIComponent(codeId)}`,
  );
  return data;
}
