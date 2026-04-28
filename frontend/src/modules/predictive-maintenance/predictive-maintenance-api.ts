import { api } from "@/lib/api";

/**
 * Typed client for the FastAPI predictive_maintenance module.
 *
 * ⚠ SPEC-FIRST — no `backend/app/modules/predictive_maintenance/` mart
 * exists yet. This file defines the contract the backend must
 * implement to feed the Phase 5 page; until then every fetch will
 * 404 in dev. The legacy AI-agent endpoints
 * `/api/v1/equipment/maintenance/{pm-due,predictions}` are **not**
 * the source — different prefix, different shape, no list/summary/
 * insights companions.
 *
 * One row per **maintenance prediction** for an equipment unit. Two
 * orthogonal classifications surface here:
 *   - **RiskTier** — `critical` / `high` / `medium` / `low` —
 *     combined likelihood + severity bucket from the agent.
 *   - **MaintSource** — `pm_overdue` (rule-based, calendar-driven)
 *     vs. `failure_prediction` (AI-derived from work-order pattern).
 *
 * Plus a free-form **FailureMode** category (engine / hydraulic /
 * electrical / drivetrain / structural / other) and a workflow
 * **MaintStatus** (open / acknowledged / scheduled / completed /
 * dismissed).
 *
 * Mutations (`acknowledge`, `schedule`, `complete`, `dismiss`)
 * update only the row's `status` field (and `scheduled_for` for
 * schedule), so the page can apply optimistic updates safely.
 *
 * Mounted at `/api/predictive-maintenance` (NOT `/api/v1/...`) — see
 * the other Phase 5 marts (`/api/bids`, `/api/cost-coding`,
 * `/api/proposals`). Note the hyphen even though the Python package
 * uses an underscore.
 */

const BASE = "/api/predictive-maintenance";

// ── Enums ────────────────────────────────────────────────────────────

export type RiskTier = "critical" | "high" | "medium" | "low";

export type MaintStatus =
  | "open"
  | "acknowledged"
  | "scheduled"
  | "completed"
  | "dismissed";

export type MaintSource = "pm_overdue" | "failure_prediction";

export type FailureMode =
  | "engine"
  | "hydraulic"
  | "electrical"
  | "drivetrain"
  | "structural"
  | "other";

export type SortField =
  | "risk_tier"
  | "days_until_due"
  | "estimated_repair_cost"
  | "estimated_downtime_hours"
  | "equipment_label"
  | "predicted_failure_date"
  | "created_at";

export type SortDir = "asc" | "desc";

// ── List ─────────────────────────────────────────────────────────────

export interface PredictionListRow {
  id: string;

  equipment_id: string;
  equipment_label: string;

  risk_tier: RiskTier;
  status: MaintStatus;
  source: MaintSource;
  failure_mode: FailureMode;

  /** ISO date — only set for `failure_prediction` rows. */
  predicted_failure_date: string | null;
  /** ISO date — only set for `pm_overdue` rows (calendar PM target). */
  pm_due_date: string | null;
  /**
   * Negative when overdue. For `failure_prediction` it counts from
   * `predicted_failure_date`; for `pm_overdue` from `pm_due_date`.
   */
  days_until_due: number | null;

  estimated_downtime_hours: number | null;
  estimated_repair_cost: number | null;

  recommended_action: string;

  /** ISO. */
  created_at: string;
  /** ISO. */
  updated_at: string;
  /** ISO — only set when status === "scheduled". */
  scheduled_for: string | null;

  age_days: number;
}

export interface PredictionListResponse {
  total: number;
  page: number;
  page_size: number;
  sort_by: string;
  sort_dir: SortDir;
  items: PredictionListRow[];
}

export interface ListParams {
  page?: number;
  page_size?: number;
  sort_by?: SortField;
  sort_dir?: SortDir;
  risk_tier?: RiskTier;
  status?: MaintStatus;
  source?: MaintSource;
  failure_mode?: FailureMode;
  equipment_id?: string;
  search?: string;
  overdue_only?: boolean;
  min_cost?: number;
}

// ── Summary ──────────────────────────────────────────────────────────

export interface PredictiveMaintenanceSummary {
  total_predictions: number;

  open_count: number;
  acknowledged_count: number;
  scheduled_count: number;
  completed_count: number;
  dismissed_count: number;

  critical_count: number; // lifetime
  high_count: number;
  medium_count: number;
  low_count: number;

  open_critical_count: number;
  open_overdue_count: number; // open && days_until_due < 0

  pm_overdue_count: number; // open && source = pm_overdue
  failure_prediction_count: number; // open && source = failure_prediction

  total_estimated_exposure: number; // sum of estimated_repair_cost across open
  total_estimated_downtime_hours: number; // sum across open
  average_age_days: number | null; // open
  oldest_open_age_days: number | null;

  distinct_equipment: number;
  distinct_failure_modes: number;
}

// ── Insights ─────────────────────────────────────────────────────────

export interface RiskTierBreakdown {
  critical: number;
  high: number;
  medium: number;
  low: number;
}

export interface MaintStatusBreakdown {
  open: number;
  acknowledged: number;
  scheduled: number;
  completed: number;
  dismissed: number;
}

export interface MaintSourceBreakdown {
  pm_overdue: number;
  failure_prediction: number;
}

export interface FailureModeBreakdown {
  engine: number;
  hydraulic: number;
  electrical: number;
  drivetrain: number;
  structural: number;
  other: number;
}

export interface AgingBreakdown {
  fresh: number; // <7 days
  mature: number; // 7–30
  stale: number; // >30
}

export interface EquipmentExposureRow {
  equipment_id: string;
  equipment_label: string;
  open_count: number;
  total_estimated_repair_cost: number;
  total_estimated_downtime_hours: number;
  worst_risk_tier: RiskTier;
}

export interface FailureModeImpactRow {
  failure_mode: FailureMode;
  open_count: number;
  total_estimated_repair_cost: number;
}

export interface TopPredictionRow {
  id: string;
  equipment_label: string;
  risk_tier: RiskTier;
  failure_mode: FailureMode;
  source: MaintSource;
  estimated_repair_cost: number | null;
  days_until_due: number | null;
  age_days: number;
}

export interface CompletedPredictionRow {
  id: string;
  equipment_label: string;
  failure_mode: FailureMode;
  status: MaintStatus; // completed | dismissed
  resolved_at: string; // ISO
}

export interface PredictiveMaintenanceInsights {
  risk_tier_breakdown: RiskTierBreakdown;
  status_breakdown: MaintStatusBreakdown;
  source_breakdown: MaintSourceBreakdown;
  failure_mode_breakdown: FailureModeBreakdown;
  aging_breakdown: AgingBreakdown;
  top_equipment_exposure: EquipmentExposureRow[];
  failure_mode_impact: FailureModeImpactRow[];
  top_by_exposure: TopPredictionRow[];
  recent_completions: CompletedPredictionRow[];
}

// ── Detail ───────────────────────────────────────────────────────────

export interface PredictionEvidence {
  label: string;
  value: string;
  link: string | null;
}

export interface RecentWorkOrder {
  wo_number: string;
  description: string | null;
  closed_at: string | null;
  cost: number | null;
}

export interface PredictionHistoryEntry {
  at: string; // ISO
  status: MaintStatus;
  note: string | null;
}

export interface PredictionDetail {
  id: string;

  equipment_id: string;
  equipment_label: string;
  equipment_class: string | null; // optional taxonomy hint

  risk_tier: RiskTier;
  status: MaintStatus;
  source: MaintSource;
  failure_mode: FailureMode;

  predicted_failure_date: string | null;
  pm_due_date: string | null;
  days_until_due: number | null;

  estimated_downtime_hours: number | null;
  estimated_repair_cost: number | null;

  recommended_action: string;
  description: string;

  created_at: string;
  updated_at: string;
  scheduled_for: string | null;
  age_days: number;

  evidence: PredictionEvidence[];
  recent_work_orders: RecentWorkOrder[];
  history: PredictionHistoryEntry[];
}

// ── Mutation bodies ──────────────────────────────────────────────────

export interface AcknowledgeBody {
  note?: string;
}

export interface ScheduleBody {
  /** ISO date — when the maintenance is planned. */
  scheduled_for: string;
  note?: string;
}

export interface CompleteBody {
  /** ISO date — defaults to now on the backend if omitted. */
  completed_at?: string;
  note?: string;
}

export interface DismissBody {
  reason?: string;
}

// ── Fetchers ─────────────────────────────────────────────────────────

export async function fetchPredictiveMaintenanceSummary(): Promise<PredictiveMaintenanceSummary> {
  const { data } = await api.get<PredictiveMaintenanceSummary>(
    `${BASE}/summary`,
  );
  return data;
}

export async function fetchPredictiveMaintenanceList(
  params: ListParams,
): Promise<PredictionListResponse> {
  const { data } = await api.get<PredictionListResponse>(`${BASE}/list`, {
    params,
  });
  return data;
}

export async function fetchPredictiveMaintenanceInsights(
  topN = 10,
): Promise<PredictiveMaintenanceInsights> {
  const { data } = await api.get<PredictiveMaintenanceInsights>(
    `${BASE}/insights`,
    {
      params: { top_n: topN },
    },
  );
  return data;
}

export async function fetchPredictionDetail(
  predictionId: string,
): Promise<PredictionDetail> {
  const { data } = await api.get<PredictionDetail>(
    `${BASE}/${encodeURIComponent(predictionId)}`,
  );
  return data;
}

// ── Mutations ────────────────────────────────────────────────────────

export async function acknowledgePrediction(
  id: string,
  body: AcknowledgeBody = {},
): Promise<PredictionDetail> {
  const { data } = await api.post<PredictionDetail>(
    `${BASE}/${encodeURIComponent(id)}/acknowledge`,
    body,
  );
  return data;
}

export async function schedulePrediction(
  id: string,
  body: ScheduleBody,
): Promise<PredictionDetail> {
  const { data } = await api.post<PredictionDetail>(
    `${BASE}/${encodeURIComponent(id)}/schedule`,
    body,
  );
  return data;
}

export async function completePrediction(
  id: string,
  body: CompleteBody = {},
): Promise<PredictionDetail> {
  const { data } = await api.post<PredictionDetail>(
    `${BASE}/${encodeURIComponent(id)}/complete`,
    body,
  );
  return data;
}

export async function dismissPrediction(
  id: string,
  body: DismissBody = {},
): Promise<PredictionDetail> {
  const { data } = await api.post<PredictionDetail>(
    `${BASE}/${encodeURIComponent(id)}/dismiss`,
    body,
  );
  return data;
}
