"""Bid-network scrapers.

One subpackage per network. ``napc_network`` covers the
``{state}bids.{com,net}`` portals operated by NAPC. Future networks
(state DOT bid tabs, BidNet Direct, etc.) will land as siblings.

Every scraper follows the contracts in ``_base.py``:

    Fetcher    — robots-aware, rate-limited HTTP
    PostParser — HTML → structured BidEvent + BidResult rows
    Pipeline   — orchestrates fetch + parse + write for one (network, state)

The pipeline writes to ``tenant_id = SHARED_NETWORK_TENANT_ID``. See
``app/services/market_intel/README.md`` for the lane discipline.
"""
