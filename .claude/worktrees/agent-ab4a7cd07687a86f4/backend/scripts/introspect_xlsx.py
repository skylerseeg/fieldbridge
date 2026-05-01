"""
One-off: dump sheet names, columns, inferred dtypes, and a null-rate sample
for every Excel file (.xlsx, .xlsm, .xlsb) in data/vista_data/. Output is
JSON on stdout.

Used by the excel_marts ingest registration pass to build column_map /
type_map / dedupe_keys per mart without guessing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "vista_data"


def _dtype_label(s: pd.Series) -> str:
    """Map a pandas dtype to the small vocabulary we use in type_map."""
    if pd.api.types.is_bool_dtype(s):
        return "bool"
    if pd.api.types.is_integer_dtype(s):
        return "int"
    if pd.api.types.is_float_dtype(s):
        return "float"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    return "str"


def introspect(path: Path) -> dict:
    out: dict = {"file": path.name, "sheets": []}
    try:
        xl = pd.ExcelFile(path)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out

    for sheet in xl.sheet_names:
        try:
            df = pd.read_excel(path, sheet_name=sheet, nrows=50)
        except Exception as e:
            out["sheets"].append(
                {"name": sheet, "error": f"{type(e).__name__}: {e}"}
            )
            continue

        cols = []
        for c in df.columns:
            s = df[c]
            null_rate = float(s.isna().mean()) if len(s) else 0.0
            sample = (
                s.dropna().astype(str).head(3).tolist() if len(s) else []
            )
            cols.append(
                {
                    "header": str(c),
                    "dtype": _dtype_label(s),
                    "null_rate": round(null_rate, 3),
                    "sample": sample,
                }
            )
        out["sheets"].append(
            {"name": sheet, "rows_sampled": int(len(df)), "columns": cols}
        )
    return out


def main() -> int:
    if not DATA_DIR.exists():
        print(f"data dir not found: {DATA_DIR}", file=sys.stderr)
        return 2

    files: list[Path] = []
    for ext in ("*.xlsx", "*.xlsm", "*.xlsb"):
        files.extend(DATA_DIR.glob(ext))
    files = sorted(files)
    result = [introspect(p) for p in files]
    json.dump(result, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
