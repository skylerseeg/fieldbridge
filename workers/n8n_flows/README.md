# n8n Flows

Store n8n workflow JSON exports here for version control. JSON files
are the source of truth; n8n's internal database mirrors them after
import.

## Live Flows

| Flow | Trigger | Action |
|------|---------|--------|
| `market_intel_daily.json` | Cron 03:00 UTC | POST `/api/v1/market-intel/admin/run-itd-pipeline` → branch on counters → alert on anomalies |

## Planned Flows

| Flow | Trigger | Action |
|------|---------|--------|
| `supplier_enrichment.json` | Daily 6AM | Run email bridge → notify AP team |
| `equipment_alert.json`     | Telematics fault | Create Vista work order → notify shop |
| `bid_coverage.json`        | New bid upload | Run bid agent → email coverage report |
| `media_ingest.json`        | SharePoint upload | Tag new photos → index in media library |

## Import procedure

n8n does not auto-load flows from this directory. Each JSON is
imported once into the running n8n instance:

1. Open `http://<n8n-host>:5678` (dev: `localhost:5678`,
   prod: per Render service URL).
2. **Workflows → Import from File**, pick the JSON.
3. Open the imported workflow and toggle **Active** to ON. The
   committed JSONs ship with `"active": false` so an accidental
   import doesn't immediately fire — the operator activates
   intentionally.
4. Set required environment variables (see per-flow section below)
   under **Settings → Environment Variables** in n8n.

After import, any change made through the n8n UI must be re-exported
(Workflows → … → **Download**) and committed back here. Drift
between this directory and what n8n is actually running is the most
common source of "I thought we fixed that" incidents.

## `market_intel_daily.json`

**Required env vars on the n8n side:**

| Variable | Purpose | Example |
|---|---|---|
| `FIELDBRIDGE_API_URL` | Base URL of the FieldBridge backend | `https://api.fieldbridge.io` |
| `FIELDBRIDGE_ADMIN_TOKEN` | JWT for a user with role=`fieldbridge_admin` | `eyJhbGciOiJIUzI1NiIs…` |
| `FIELDBRIDGE_ALERT_WEBHOOK` | URL the IF-anomalies branch posts to | `https://hooks.slack.com/services/T…/B…/…` |

**Cron expression:** `0 3 * * *` — once per day at 03:00 UTC. ITD's
`apps.itd.idaho.gov` is lower-traffic in this window. Edit the Cron
node if you want a different time.

**Anomaly branch fires when:**

  * `skipped_parse_error > 0` — every error is meaningful here
    because slice-2's parser exits cleanly on every known
    template variant. A non-zero count signals either a brand-new
    AASHTOWare template (re-capture fixtures, update parser
    anchors) or a corrupt PDF (rare).
  * `skipped_fetch_error > 5` — broader ITD outage. Less than 5
    fetch errors per night is probably normal apex flakiness; more
    than 5 means you should be aware.

The OK branch logs a single-line summary into the n8n execution
record. Trend the counters over a week and you'll see the steady
state for `written` (new abstracts published), `skipped_already_ingested`
(re-fetched but unchanged), and `skipped_legacy_template` (tail of
old AASHTOWare reports — populated by v1.5b's backfill worker).

**Backend endpoint contract:**

  * `POST /api/v1/market-intel/admin/run-itd-pipeline`
  * Auth: Bearer JWT, role=`fieldbridge_admin`
  * Returns: `ITDPipelineRunResponse` (the canonical 9-key counters
    dict from `app/modules/market_intel/schema.py`)
  * Hard failures (5xx upstream, robots-deny on the index page,
    network) return the counters dict with zeros — never an HTTP
    error. The IF node branches on counters, not status.

**v1 → main merge gate:** this flow ships with `"active": false`. It
should stay inactive on `feature/market-intel-v15` and only flip to
true after the branch merges to `main` and Render's n8n service
reloads. Pre-loaded but inert — see `docs/agent_board.md` close-out
note for the strategic phasing.
