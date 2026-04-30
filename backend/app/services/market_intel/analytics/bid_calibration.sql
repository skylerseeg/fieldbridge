-- bid_calibration.sql
--
-- One row per bid the caller's contractor name submitted, joined
-- with the per-event low-bidder amount. The service function
-- groups by quarter (calendar Q1-Q4) in Python — quarter-truncation
-- syntax differs between SQLite and Postgres, and Python's
-- ``date.month`` arithmetic is portable.
--
-- Match strategy: case-insensitive substring (LOWER(name) LIKE
-- LOWER(<pattern>)) — Postgres has ILIKE, SQLite has it via
-- collation hacks; LOWER+LIKE works in both without configuration.
-- The pattern is wrapped in % wildcards by the caller.
--
-- Bind parameters:
--   caller_tenant         caller's tenant_id
--   shared_network_tenant SHARED_NETWORK_TENANT_ID
--   contractor_pattern    LIKE pattern, e.g. "%van con%"

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
    be.bid_open_date AS bid_open_date,
    be.id            AS bid_event_id
FROM bid_events AS be
JOIN bid_results AS br ON br.bid_event_id = be.id
WHERE be.tenant_id IN (:caller_tenant, :shared_network_tenant)
  AND LOWER(br.contractor_name) LIKE LOWER(:contractor_pattern)
  AND be.bid_open_date IS NOT NULL
ORDER BY be.bid_open_date
