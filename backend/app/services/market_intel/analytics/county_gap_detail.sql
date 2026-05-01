-- county_gap_detail.sql
--
-- Per-event detail rows for ONE (state, county) cell of the
-- opportunity_gaps surface. Returns up to 200 bid events in that
-- geography within the dollar/time window where the caller's
-- contractor name does NOT appear in the bidder list — i.e. "public
-- awards we weren't part of."
--
-- Tenant scoping mirrors the rest of Market Intel: union the caller's
-- tenant_id with the shared-network sentinel so scraped public bids
-- (which live on the shared tenant) are visible.
--
-- The "caller never bid" filter uses the same case-insensitive
-- substring match as bid_calibration.sql:
--   NOT EXISTS (
--       SELECT 1 FROM bid_results br
--       WHERE br.bid_event_id = be.id
--         AND LOWER(br.contractor_name) LIKE LOWER(:caller_pattern)
--   )
-- Until VanCon's contractor identity is properly resolved (v3 of the
-- contractor-resolution layer), this is the best heuristic we have.
-- If the pattern matches NOTHING in the dataset (which is the case
-- before VanCon's bids land on shared-network), the NOT EXISTS
-- clause has no filtering effect and every event in the geo passes
-- through — same behavior as the aggregate opportunity_gaps query.
--
-- Bind parameters:
--   caller_tenant         caller's tenant_id (UUID v4 string)
--   shared_network_tenant SHARED_NETWORK_TENANT_ID
--   state_code            2-letter USPS code (uppercase)
--   county                county name — must match the
--                         opportunity_gaps GROUP BY label exactly
--                         (case-sensitive, including spaces)
--   bid_min               low_bid_amount >= this
--   bid_max               low_bid_amount <= this
--   cutoff_date           bid_open_date >= this
--   caller_pattern        LIKE pattern wrapped in % (e.g. "%van con%")

SELECT
    be.id              AS bid_event_id,
    be.project_title   AS project_title,
    be.project_owner   AS project_owner,
    be.solicitation_id AS solicitation_id,
    be.source_url      AS source_url,
    be.source_state    AS source_state,
    be.source_network  AS source_network,
    be.bid_open_date   AS bid_open_date,
    be.location_state  AS location_state,
    be.location_county AS location_county,
    be.csi_codes       AS csi_codes,
    low.contractor_name AS low_bidder_name,
    low.bid_amount      AS low_bid_amount
FROM bid_events AS be
JOIN bid_results AS low
  ON low.bid_event_id = be.id
 AND low.is_low_bidder = TRUE
WHERE be.tenant_id IN (:caller_tenant, :shared_network_tenant)
  AND be.location_state  = :state_code
  AND be.location_county = :county
  AND be.bid_open_date IS NOT NULL
  AND be.bid_open_date >= :cutoff_date
  AND low.bid_amount BETWEEN :bid_min AND :bid_max
  AND NOT EXISTS (
      SELECT 1 FROM bid_results br
      WHERE br.bid_event_id = be.id
        AND LOWER(br.contractor_name) LIKE LOWER(:caller_pattern)
  )
ORDER BY be.bid_open_date DESC
LIMIT 200
