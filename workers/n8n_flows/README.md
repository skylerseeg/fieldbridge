# n8n Flows

Store n8n workflow JSON exports here for version control.

## Planned Flows
| Flow | Trigger | Action |
|------|---------|--------|
| `supplier_enrichment.json` | Daily 6AM | Run email bridge → notify AP team |
| `equipment_alert.json`     | Telematics fault | Create Vista work order → notify shop |
| `bid_coverage.json`        | New bid upload | Run bid agent → email coverage report |
| `media_ingest.json`        | SharePoint upload | Tag new photos → index in media library |

Export flows from n8n and commit JSON here.
