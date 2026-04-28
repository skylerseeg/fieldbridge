# email_bridge
M365/Exchange email scanner for supplier enrichment.
Extracts vendor contact data and infers CSI codes from email signatures
and body text. Outputs Vista-ready CSV for AP Vendor import.

## Files
- `fieldbridge_supplier_enrichment.py` — Main pipeline (v1 complete)
- `csi_codes.py`                       — 4-digit CSI lookup dict
- `deduplicator.py`                    — RapidFuzz vendor merge
- `vista_exporter.py`                  — CSV formatters for Vista import
