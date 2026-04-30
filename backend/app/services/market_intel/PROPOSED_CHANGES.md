# PROPOSED_CHANGES: document the dual cron-trigger pattern

**For Lead** — request to mirror a paragraph into `docs/market-intel.md`
on PR review. The split between Render-native cron and n8n HTTP cron
is intentional (Lead's option-C call on the cron-piece slice) but
the next worker won't know that without doc-level capture.

## Suggested section in `docs/market-intel.md`

Add under "Architecture" or as a new "Operations" section:

> ### Nightly cron — dual triggers
>
> The ITD ingest pipeline (`ITDPipeline.run_state("ID", db)`) is
> wired to fire from **two** schedulers, by design:
>
> | Trigger | Path | Role | Owner |
> |---|---|---|---|
> | **Render cron service** | `backend/scripts/run_itd_pipeline.py` against the prod DB via `DATABASE_URL` | Production primary — runs nightly, no HTTP hop | Render `fieldbridge-itd-pipeline` cron entry in `render.yaml` |
> | **n8n HTTP cron** | `POST /api/v1/market-intel/admin/run-itd-pipeline` (gated by `require_admin`) | Ad-hoc admin runs, replay after fixture-format changes, alerting branch on anomaly counters | `workers/n8n_flows/market_intel_daily.json` |
>
> Both call the same `ITDPipeline` class, so DB writes are idempotent
> across either trigger (the `(tenant_id, source_url, raw_html_hash)`
> unique constraint dedups). In steady state Render is the primary; n8n is
> intentionally inactive (`"active": false`) on import and only flipped on
> if/when the operator wants UI-driven runs + Slack-style alerting.
>
> When deduplication is desired (e.g. one of the two paths starts
> running consistently first), keep both wired — the redundant call
> just reports `skipped_already_ingested = N` and exits cleanly.

## Why both

Lead's option-C decision (recorded in this branch's PR for the
cron-piece slice):

  - Render cron is simpler, fewer moving parts, prod-primary fit.
  - n8n adds observability (IF-anomalies branch, webhook alert)
    and ad-hoc trigger UX without another deploy.
  - Idempotency at the DB layer means dual triggers can't double-write.

## Lane note

This file lives at `app/services/market_intel/PROPOSED_CHANGES.md`
because it was authored by the Backend Worker (whose lane is this
service folder). The actual doc edit goes into `docs/market-intel.md`
(Lead-owned). When the section lands in the design doc, this
PROPOSED_CHANGES.md can be deleted.
