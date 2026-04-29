"""Market Intel module — public bid-network analytics.

Reads ``bid_events`` and ``bid_results`` (cross-tenant via the
shared-network sentinel) plus per-tenant Vista context to deliver:

  * Competitor pricing curves (median rank × premium-over-low)
  * Opportunity gaps (geographies VanCon doesn't compete in)
  * Bid calibration (VanCon's own win rate over time)

See ``docs/market-intel.md`` for the full design and
``backend/app/services/market_intel/`` for the scraper/ingest pipeline.
This module owns ONLY the read API; writes are handled by the service
layer + n8n nightly cron.
"""
from app.modules.market_intel.router import router

__all__ = ["router"]
