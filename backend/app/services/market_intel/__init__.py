"""Market Intel service — bid network scrapers, normalizers, analytics.

Architecture summary (full design: ``docs/market-intel.md``):

    scrapers/        — per-network HTTP fetchers + HTML parsers
    normalizers/     — CSI inference, contractor resolution, geo cleanup
    analytics/       — SQL templates returned by the read API
    pipeline.py      — per-state orchestrator, called by n8n cron

Writes land in ``app.models.bid_event``, ``bid_result``, ``contractor``
under ``tenant_id = SHARED_NETWORK_TENANT_ID``. Customer-tenant reads
union their own tenant_id with that sentinel.

This is a STUB scaffold. Implementation is the Market Intel Backend
Worker's first task — see ``backend/app/modules/market_intel/PROPOSED_CHANGES.md``.
"""
