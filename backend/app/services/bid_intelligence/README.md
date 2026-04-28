# bid_intelligence
Agent that parses bid drawings (PDF/DWG) and spec documents to extract
a material + quantity list, then compares it against supplier quotes
received via email to verify full coverage.

## Flow
1. Upload drawings + specs (PDF)
2. `drawing_parser.py` — OCR + AI extraction → material list
3. `spec_parser.py`    — Parse Division specs for material requirements
4. `quote_ingester.py` — Pull supplier quote emails from M365
5. `coverage_checker.py` — Claude agent: compare list vs quotes → gap report

## Output
- `material_list.json`   — structured BOM from drawings/specs
- `coverage_report.json` — which items are covered, which are missing
- Vista-ready: populate bid cost codes from coverage data
