-- opportunity_gaps.sql
--
-- Counties / states where similar-scope public work happens. v1.5
-- semantic: every event in the shared dataset is a candidate
-- "missed opportunity" cell. v3 will narrow this with a per-tenant
-- "did the caller bid here" filter once we have a way to identify
-- the caller's contractor name across tenants.
--
-- The query GROUPs by state + county here — neither operation is
-- dialect-specific, so we keep the aggregation in SQL and let
-- Python only assemble the Pydantic rows.
--
-- Bind parameters:
--   caller_tenant         caller's tenant_id
--   shared_network_tenant SHARED_NETWORK_TENANT_ID
--   bid_min               low_bid >= this
--   bid_max               low_bid <= this
--   cutoff_date           bid_open_date >= this
--
-- Output: one row per (state, county) cell with missed_count and
-- avg_low_bid. ``top_scope_codes`` is filled in by the service
-- function (currently empty list — csi_codes is null until the
-- email_bridge.csi_inference normalizer runs against bid_events,
-- which is post-v1.5b).

SELECT
    be.location_state  AS state,
    be.location_county AS county,
    COUNT(DISTINCT be.id) AS missed_count,
    AVG(low.bid_amount) AS avg_low_bid
FROM bid_events AS be
JOIN bid_results AS low
  ON low.bid_event_id = be.id
 AND low.is_low_bidder = TRUE
WHERE be.tenant_id IN (:caller_tenant, :shared_network_tenant)
  AND low.bid_amount BETWEEN :bid_min AND :bid_max
  AND be.bid_open_date IS NOT NULL
  AND be.bid_open_date >= :cutoff_date
  AND be.location_state IS NOT NULL
GROUP BY be.location_state, be.location_county
ORDER BY missed_count DESC, be.location_state, be.location_county
