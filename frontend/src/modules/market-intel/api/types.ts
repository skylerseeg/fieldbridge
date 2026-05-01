/**
 * Market Intel — typed wire contract.
 *
 * Mirrors `backend/app/modules/market_intel/schema.py` 1:1. Any change
 * here MUST have a matching change there. The backend is the source of
 * truth; if the two drift the runtime quietly degrades to mock-data
 * mode behavior on real responses.
 *
 * Endpoints (mounted at `/api/market-intel/*` — note the hyphen, the
 * Python package uses an underscore):
 *
 *   GET /competitor-curves
 *     ?states=UT,ID&months_back=36&min_bids=10  → CompetitorCurveRow[]
 *
 *   GET /opportunity-gaps
 *     ?bid_min=250000&bid_max=5000000&months_back=24 → OpportunityRow[]
 *
 *   GET /gap/{state}/{county}
 *     ?bid_min=250000&bid_max=5000000&months_back=24 → CountyGapEvent[]
 *
 *   GET /bid-calibration
 *     ?contractor_name_match=van%20con           → CalibrationPoint[]
 *
 * All three currently return `[]` from the live backend during dark
 * accumulation; the front-end is expected to handle empty gracefully.
 */

/** One competitor's pricing personality across the network. */
export interface CompetitorCurveRow {
  contractor_name: string;
  bid_count: number;
  /** Decimal premium over low bid; 0.05 = 5% above the winner. */
  avg_premium_over_low: number;
  /** 1 = always low bidder; higher = consistently further from low. */
  median_rank: number;
  /** 0–1. */
  win_rate: number;
}

/** One county-or-state cell where similar-scope work happened
 *  but VanCon never bid. */
export interface OpportunityRow {
  /** Two-letter state code, uppercase. */
  state: string;
  /** County name; null when the row is state-level only. */
  county: string | null;
  missed_count: number;
  avg_low_bid: number;
  /** CSI scope codes that dominated the missed work. */
  top_scope_codes: string[];
}

/** One bid event in an opportunity-gap county where VanCon never bid.
 *  Returned by `GET /gap/{state}/{county}` — drill-in from the
 *  Opportunity gaps top-N list. */
export interface CountyGapEvent {
  bid_event_id: string;
  project_title: string;
  /** Owning agency (e.g. "ITD", "City of Boise"). May be null. */
  project_owner: string | null;
  /** Vendor-published bid number; may be null. */
  solicitation_id: string | null;
  /** Source URL (DOT bid abstract PDF, NAPC posting, etc.). */
  source_url: string;
  /** 2-letter state of the SCRAPER (always uppercase). */
  source_state: string;
  /** Network identifier — `state_dot_id` | `napc` | etc. */
  source_network: string;
  /** ISO date — YYYY-MM-DD. */
  bid_open_date: string;
  /** 2-letter state of the PROJECT (always uppercase). */
  location_state: string;
  /** County name; null when the row is state-level only. */
  location_county: string | null;
  csi_codes: string[];
  /** Winning low bidder name. */
  low_bidder_name: string;
  /** Winning bid in USD. */
  low_bid_amount: number;
}

/** One quarter of the contractor's own bid calibration. */
export interface CalibrationPoint {
  /** ISO date — first day of the quarter (YYYY-MM-DD). */
  quarter: string;
  bids_submitted: number;
  wins: number;
  avg_rank: number;
  /** Decimal premium over low for losing bids; null = no losses or no data. */
  pct_above_low: number | null;
}

// ── Request param shapes ────────────────────────────────────────────

export interface CompetitorCurvesParams {
  /** Two-letter state codes. Sent as a comma-joined query string. */
  states: string[];
  /** 12 / 24 / 36. */
  monthsBack: number;
  /** Server-side filter: minimum bid_count for a contractor to appear. */
  minBids: number;
}

export interface OpportunityGapsParams {
  bidMin: number;
  bidMax: number;
  monthsBack: number;
}

export interface CountyGapDetailParams {
  /** 2-letter state code, uppercase. */
  state: string;
  /** County name; the URL component the page reads from `useParams`. */
  county: string;
  bidMin: number;
  bidMax: number;
  monthsBack: number;
  /** Optional ILIKE substring; events where ANY bidder matches are
   *  filtered out. Defaults to backend's "van con" if omitted. */
  contractorNameMatch?: string;
}

export interface BidCalibrationParams {
  /** Substring match against contractor_name; default "van con". */
  contractorNameMatch: string;
}
