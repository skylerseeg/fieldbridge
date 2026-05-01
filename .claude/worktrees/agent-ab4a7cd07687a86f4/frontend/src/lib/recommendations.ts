import { api } from "@/lib/api";

/**
 * Typed client for the Phase-6 LLM-recommendations endpoints.
 *
 * Every module that wires up the right rail mounts the same shape:
 *   GET /api/<module>/recommendations -> InsightResponse
 *
 * That payload is produced by `app.core.llm.generate_insight` and
 * cached in the `llm_insights` table for `DEFAULT_TTL_HOURS` (6h)
 * per `(tenant, module)`. The cache invalidates on data change
 * (revision-token mismatch) so right-rail advice never lags the
 * underlying numbers by more than a few minutes once the user
 * scrolls back through.
 *
 * SHAPE — must mirror `app.core.llm.InsightResponse`. If you add a
 * field to either side, add it here too. The frontend only renders
 * fields it recognizes, so adding new ones server-side is forward-
 * compatible — but renaming or removing is a breaking change.
 *
 * STUB MODE — when `ANTHROPIC_API_KEY` is unset on the backend (e.g.
 * dev machines without a key), the response will have
 * `is_stub: true` and a single INFO-severity row explaining the
 * gap. The right rail renders that row with a different visual to
 * cue the operator that they're not yet seeing live recommendations.
 */

export type Severity = "critical" | "warning" | "info";

export interface Recommendation {
  title: string;
  severity: Severity;
  rationale: string;
  suggested_action: string;
  affected_assets: string[];
}

export interface InsightResponse {
  module: string;
  generated_at: string; // ISO
  model: string;
  revision_token: string;
  recommendations: Recommendation[];
  input_tokens: number;
  output_tokens: number;
  is_stub: boolean;
}

export interface FetchRecommendationsParams {
  /**
   * When true, bypass the 6h cache and force a fresh Claude call.
   * Reserved for the (not-yet-wired) admin Regenerate button —
   * default UX should never set this, since it costs money.
   */
  refresh?: boolean;
}

/**
 * Builds the `/api/<module>/recommendations` URL the same way every
 * Phase-5 module client does — the prefix is a bare `/api/<slug>`,
 * NOT `/api/v1/<slug>`. See `equipment-api.ts` for the rationale.
 */
export async function fetchRecommendations(
  module: string,
  params: FetchRecommendationsParams = {},
): Promise<InsightResponse> {
  const { data } = await api.get<InsightResponse>(
    `/api/${module}/recommendations`,
    { params },
  );
  return data;
}
