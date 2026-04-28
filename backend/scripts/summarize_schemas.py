"""Print a compact per-file summary of the introspection snapshot."""
import json
import sys
from pathlib import Path

SNAP = Path(__file__).with_name("_schemas_snapshot.json")
data = json.loads(SNAP.read_text(encoding="utf-8"))

for entry in data:
    print(f"\n### {entry['file']}")
    if "error" in entry:
        print(f"  ERROR: {entry['error']}")
        continue
    for sheet in entry["sheets"]:
        if "error" in sheet:
            print(f"  sheet '{sheet['name']}': ERROR {sheet['error']}")
            continue
        print(f"  sheet '{sheet['name']}'  ({sheet['rows_sampled']} rows sampled, {len(sheet['columns'])} cols)")
        for c in sheet["columns"]:
            nr = c["null_rate"]
            flag = " [ALL-NULL]" if nr >= 0.999 else (" [sparse]" if nr >= 0.7 else "")
            print(f"    - {c['header']!r:45s}  {c['dtype']:8s}  null={nr:.2f}{flag}")
