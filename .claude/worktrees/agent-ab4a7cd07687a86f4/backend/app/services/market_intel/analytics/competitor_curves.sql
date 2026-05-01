-- competitor_curves.sql
--
-- Returns one row per (bidder, bid_event) joined with the per-event
-- low-bid amount. The service function aggregates by contractor in
-- Python (computes bid_count, avg_premium_over_low, median_rank,
-- win_rate) — keeps the query cross-dialect.
--
-- Tenant scoping: union the caller's tenant_id with the shared-network
-- sentinel. Public ITD-sourced rows live under the sentinel; per-tenant
-- private overlays (v3) live under the caller's own id.
--
-- Bind parameters:
--   caller_tenant         caller's tenant_id (UUID v4 string)
--   shared_network_tenant SHARED_NETWORK_TENANT_ID
--   state_codes           expanding bind: list of 2-letter USPS codes
--   cutoff_date           bid_open_date >= this
--
-- The LEFT JOIN against the per-event low row is computed via a
-- correlated subquery so we don't need a CTE (CTEs work in modern
-- SQLite + Postgres but the subquery form is the most universally
-- portable shape).

SELECT
    br.contractor_name AS contractor_name,
    br.bid_amount      AS bid_amount,
    br.rank            AS rank,
    br.is_low_bidder   AS is_low_bidder,
    (
        SELECT low.bid_amount
        FROM bid_results AS low
        WHERE low.bid_event_id = be.id
          AND low.is_low_bidder = TRUE
        LIMIT 1
    ) AS low_amount,
    be.location_state  AS location_state,
    be.bid_open_date   AS bid_open_date
FROM bid_events AS be
JOIN bid_results AS br ON br.bid_event_id = be.id
WHERE be.tenant_id IN (:caller_tenant, :shared_network_tenant)
  AND be.location_state IN :state_codes
  AND be.bid_open_date IS NOT NULL
  AND be.bid_open_date >= :cutoff_date
