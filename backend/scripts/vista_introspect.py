"""Vista SQL introspection — operator tool for mapping a Vista database.

Connects via the shared ``app.core.tenant.get_vista_connection_for_tenant``
helper (pyodbc + msodbcsql17, baked into the API service image). Runs
read-only INFORMATION_SCHEMA + sys catalog queries, produces:

  * Server identity (version, edition, current DB, current user)
  * Full table inventory with row counts (sys.partitions)
  * Tables grouped by Vista module prefix (JC = Job Cost, EM = Equipment,
    AP = AP, AR = AR, PR = Payroll, HQ = Headquarters, GL = General
    Ledger, IN = Inventory, SM = Service Management, PM = Project
    Management, PO = Purchase Order, SL = Subcontract, BD = Bidding,
    MS = Material Sales)
  * Top 25 tables by row count (the data-rich surfaces)
  * Column inventory for "key" tables (the canonical Vista entities
    documented in data/vista_schemas/ + the most common analytics
    targets)
  * Foreign key relationships (for cross-module join paths)
  * Date-column freshness checks on key tables

Read-only by hard rule (CLAUDE.md): every query is SELECT-only.

Usage:

    cd backend
    python scripts/vista_introspect.py                 # full, default
    python scripts/vista_introspect.py --mode peek     # ~5s smoke check
    python scripts/vista_introspect.py --output /tmp/vista_map.json
    python scripts/vista_introspect.py --extra-key-tables jcjmd,phgr

Why a wrapper script vs ``python -m``: same rationale as
``run_napc_probe.py`` and ``run_itd_pipeline.py`` — running the module
under -m makes it ``__main__`` and breaks downstream imports. Wrapper
imports everything as normal modules so app.core.* works cleanly.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

# sys.path bootstrap — same pattern as run_napc_probe.py.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.core.tenant import get_vista_connection_for_tenant  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402

log = logging.getLogger("fieldbridge.vista_introspect")


# ---------------------------------------------------------------------------
# Vista module prefix map. Two-letter prefix on table names is the
# canonical Trimble Vista convention. Add to this map as new prefixes
# surface in the inventory.

VISTA_MODULE_PREFIXES: dict[str, str] = {
    "JC": "Job Cost",
    "EM": "Equipment",
    "AP": "Accounts Payable",
    "AR": "Accounts Receivable",
    "PR": "Payroll",
    "HQ": "Headquarter / Global",
    "HR": "Human Resources",
    "GL": "General Ledger",
    "CM": "Cash Management",
    "IN": "Inventory",
    "MS": "Material Sales",
    "PM": "Project Management",
    "PO": "Purchase Order",
    "SL": "Subcontract",
    "SM": "Service Management",
    "BD": "Bidding",
    "FA": "Fixed Assets",
    "VA": "VendorPay / ACH",
    "DM": "Document Management",
    "RP": "Reporting",
    "vp": "Viewpoint Internal",  # lowercase prefix
}


# Canonical "key" tables. Curated list = anchors per Vista module; deep
# introspection runs against these for the column-inventory + freshness
# pass. Pass --extra-key-tables to add more on a per-run basis.
KEY_TABLES: tuple[str, ...] = (
    # Per CLAUDE.md / data/vista_schemas/ documented set
    "apvend", "emem", "emwo",
    # Job Cost backbone — these are what FieldBridge marts mostly land
    # against in the long-arc Vista REST migration
    "jcco", "jcjm", "jcci", "jcjt", "jcjp", "jcjs",
    # AP transactions
    "aphd", "apld", "apph", "appl",
    # PO / receiving
    "pohd", "pold", "porg",
    # Equipment activity
    "emct", "emrc", "emcd", "emcl",
    # Payroll
    "premp", "prtt", "prte", "prdt",
    # GL
    "glco", "glmt", "glca",
    # Headquarter / lookup
    "hqco", "hqys",
)


# ---------------------------------------------------------------------------
# Tenant fetch — produces a Tenant object with Vista creds populated
# (either from the DB row, or as a fallback, from settings env vars).

async def _get_vancon_tenant() -> Tenant:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Tenant).where(Tenant.slug == settings.vancon_tenant_slug)
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise RuntimeError(
                f"VanCon tenant not found (slug={settings.vancon_tenant_slug}). "
                "Run `python -m app.core.seed` first."
            )

    # Detach from the session so we can mutate the field shadows below
    # without SQLAlchemy thinking we're trying to write back.
    if not tenant.vista_sql_host:
        log.info(
            "Tenant.vista_sql_host is empty — falling back to env var defaults "
            "from settings (Settings reads VISTA_SQL_* directly)."
        )
        tenant.vista_sql_host = settings.vista_sql_host
        tenant.vista_sql_port = settings.vista_sql_port or 1433
        tenant.vista_sql_db = settings.vista_sql_db
        tenant.vista_sql_user = settings.vista_sql_user
        tenant.vista_sql_password = settings.vista_sql_password

    if not tenant.vista_sql_host:
        raise RuntimeError(
            "Vista SQL host not configured on the VanCon tenant row OR in "
            "settings env vars (VISTA_SQL_HOST). Configure via the "
            "onboarding wizard or set the env var on the Render service."
        )
    return tenant


# ---------------------------------------------------------------------------
# Introspection queries. All read-only. All use parameter substitution
# where needed so identifier injection isn't a concern.

def _server_identity(cursor) -> dict[str, Any]:
    cursor.execute("SELECT @@VERSION, DB_NAME(), CURRENT_USER, SUSER_SNAME()")
    row = cursor.fetchone()
    version_full = row[0]
    # First line of @@VERSION is the human-readable name; rest is build info.
    version_short = version_full.split("\n")[0].strip()
    return {
        "server_version_short": version_short,
        "server_version_full": version_full,
        "current_database": row[1],
        "current_user": row[2],
        "login_name": row[3],
    }


def _table_inventory(cursor) -> list[dict[str, Any]]:
    """All user tables with row counts. ``index_id IN (0,1)`` covers
    heap (0) and clustered (1) so we count physical rows once per table."""
    cursor.execute("""
        SELECT s.name AS schema_name,
               t.name AS table_name,
               COALESCE(SUM(p.rows), 0) AS row_count
          FROM sys.tables t
          JOIN sys.schemas s ON s.schema_id = t.schema_id
          LEFT JOIN sys.partitions p
            ON p.object_id = t.object_id
           AND p.index_id IN (0, 1)
         GROUP BY s.name, t.name
         ORDER BY COALESCE(SUM(p.rows), 0) DESC, s.name, t.name
    """)
    return [
        {"schema": s, "table": t, "rows": int(rc)}
        for s, t, rc in cursor.fetchall()
    ]


def _columns_for(cursor, table_name: str) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT COLUMN_NAME,
               DATA_TYPE,
               IS_NULLABLE,
               CHARACTER_MAXIMUM_LENGTH,
               NUMERIC_PRECISION,
               NUMERIC_SCALE
          FROM INFORMATION_SCHEMA.COLUMNS
         WHERE TABLE_NAME = ?
         ORDER BY ORDINAL_POSITION
        """,
        table_name,
    )
    out: list[dict[str, Any]] = []
    for col, dt, nul, ml, np, ns in cursor.fetchall():
        col_info: dict[str, Any] = {
            "col": col,
            "type": dt,
            "nullable": nul == "YES",
        }
        if ml is not None:
            col_info["length"] = int(ml) if ml >= 0 else "max"
        if np is not None:
            col_info["precision"] = int(np)
        if ns is not None:
            col_info["scale"] = int(ns)
        out.append(col_info)
    return out


def _foreign_keys(cursor) -> list[dict[str, Any]]:
    cursor.execute("""
        SELECT fk.name                              AS fk_name,
               OBJECT_NAME(fk.parent_object_id)     AS source_table,
               cs.name                              AS source_column,
               OBJECT_NAME(fk.referenced_object_id) AS target_table,
               ct.name                              AS target_column
          FROM sys.foreign_keys fk
          JOIN sys.foreign_key_columns fkc
            ON fkc.constraint_object_id = fk.object_id
          JOIN sys.columns cs
            ON cs.object_id = fkc.parent_object_id
           AND cs.column_id = fkc.parent_column_id
          JOIN sys.columns ct
            ON ct.object_id = fkc.referenced_object_id
           AND ct.column_id = fkc.referenced_column_id
         ORDER BY OBJECT_NAME(fk.parent_object_id), fk.name
    """)
    return [
        {
            "fk_name": fn,
            "source_table": st,
            "source_col": sc,
            "target_table": tt,
            "target_col": tc,
        }
        for fn, st, sc, tt, tc in cursor.fetchall()
    ]


def _date_freshness(cursor, table: str, columns: list[dict[str, Any]]) -> dict[str, Any] | None:
    """For tables with a date-typed column, get min/max + row count.

    Picks the first date/datetime column. For tables with multiple
    date columns, the earliest-defined one is the "primary" date —
    typically the transaction date in Vista.
    """
    date_col = None
    for c in columns:
        if c["type"].lower() in ("date", "datetime", "datetime2", "smalldatetime"):
            date_col = c["col"]
            break
    if not date_col:
        return None
    # Identifier injection safe: date_col + table come from sys catalog.
    try:
        cursor.execute(
            f"SELECT MIN([{date_col}]), MAX([{date_col}]), COUNT(*) FROM [{table}]"
        )
        row = cursor.fetchone()
        return {
            "date_column": date_col,
            "min_date": row[0],
            "max_date": row[1],
            "row_count_with_date": int(row[2]),
        }
    except Exception as exc:  # pragma: no cover — defensive
        log.warning("Freshness check failed for %s.%s: %s", table, date_col, exc)
        return None


# ---------------------------------------------------------------------------
# Reporting

def _group_by_module(inventory: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_prefix: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in inventory:
        t = row["table"]
        prefix = t[:2].upper() if len(t) >= 2 else "??"
        by_prefix[prefix].append(row)
    return {
        prefix: {
            "module": VISTA_MODULE_PREFIXES.get(prefix, "Unknown / non-Vista"),
            "table_count": len(tables),
            "total_rows": sum(t["rows"] for t in tables),
        }
        for prefix, tables in by_prefix.items()
    }


def _print_summary(report: dict[str, Any]) -> None:
    s = report["server"]
    print()
    print("=" * 70)
    print("Vista SQL Introspection Report")
    print("=" * 70)
    print(f"  Server   : {s['server_version_short']}")
    print(f"  Database : {s['current_database']}")
    print(f"  User     : {s['current_user']}  (login: {s['login_name']})")
    print(f"  Captured : {report['captured_at']}")

    if "table_count" in report:
        print(f"\n  PEEK MODE — total user tables: {report['table_count']}")
        return

    inv = report.get("tables", [])
    print(f"\n  Total user tables : {len(inv):,}")
    print(f"  Total rows        : {sum(t['rows'] for t in inv):,}")

    print("\n--- Modules (by Vista 2-letter prefix) ---")
    mods = report["modules"]
    for prefix in sorted(mods.keys(), key=lambda p: -mods[p]["total_rows"]):
        m = mods[prefix]
        print(f"  {prefix:>3} {m['module']:<28} {m['table_count']:>4} tables  {m['total_rows']:>14,} rows")

    print("\n--- Top 25 tables by row count ---")
    for r in report["top_25_by_rows"]:
        print(f"  {r['schema']}.{r['table']:<24} {r['rows']:>14,}")

    print("\n--- Key tables (column counts + freshness) ---")
    for tname, info in sorted(report["key_table_columns"].items()):
        cc = len(info["columns"])
        f = info.get("freshness")
        if f:
            print(f"  {tname:<10} {cc:>3} cols  date={f['date_column']:<24} {f['min_date']} -> {f['max_date']}  ({f['row_count_with_date']:,} rows)")
        else:
            print(f"  {tname:<10} {cc:>3} cols  (no date column for freshness check)")
    missing = sorted(report.get("key_tables_missing", []))
    if missing:
        print(f"\n  Key tables NOT FOUND in this DB: {', '.join(missing)}")

    fks = report.get("foreign_keys", [])
    print(f"\n--- Foreign keys ---")
    print(f"  Total constraints: {len(fks)}")
    if fks:
        # Show top 10 most-referenced target tables
        target_count: dict[str, int] = defaultdict(int)
        for fk in fks:
            target_count[fk["target_table"]] += 1
        top_targets = sorted(target_count.items(), key=lambda x: -x[1])[:10]
        print("  Top FK target tables (i.e. most-joined-into):")
        for tt, cnt in top_targets:
            print(f"    {tt:<28} {cnt} inbound FKs")


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


# ---------------------------------------------------------------------------
# Main

def main() -> int:
    parser = argparse.ArgumentParser(description="Vista SQL introspection.")
    parser.add_argument(
        "--mode",
        choices=["peek", "full"],
        default="full",
        help="`peek` = server identity + table count only (~5s). "
             "`full` = full inventory + columns + FKs + freshness (~30-60s).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="JSON report path. Default: /tmp/vista_introspection_<db>.json",
    )
    parser.add_argument(
        "--extra-key-tables",
        type=lambda s: [t.strip() for t in s.split(",") if t.strip()],
        default=[],
        help="Comma-separated table names to include in the column-inventory "
             "+ freshness pass beyond the canonical KEY_TABLES set.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    # Tenant + connection.
    tenant = asyncio.run(_get_vancon_tenant())
    log.info(
        "Connecting to Vista: %s:%s/%s as %s",
        tenant.vista_sql_host,
        tenant.vista_sql_port,
        tenant.vista_sql_db,
        tenant.vista_sql_user,
    )
    conn = get_vista_connection_for_tenant(tenant)
    cursor = conn.cursor()

    report: dict[str, Any] = {
        "tenant_slug": tenant.slug,
        "captured_at": datetime.utcnow().isoformat() + "Z",
        "mode": args.mode,
        "server": _server_identity(cursor),
    }

    if args.mode == "peek":
        cursor.execute("SELECT COUNT(*) FROM sys.tables")
        report["table_count"] = int(cursor.fetchone()[0])
    else:
        log.info("Fetching full table inventory + row counts...")
        inv = _table_inventory(cursor)
        report["tables"] = inv
        report["modules"] = _group_by_module(inv)
        report["top_25_by_rows"] = inv[:25]

        log.info("Introspecting key tables...")
        all_keys = list(KEY_TABLES) + list(args.extra_key_tables)
        existing_table_names = {t["table"].lower() for t in inv}

        report["key_table_columns"] = {}
        report["key_tables_missing"] = []
        for kt in all_keys:
            if kt.lower() not in existing_table_names:
                report["key_tables_missing"].append(kt)
                continue
            cols = _columns_for(cursor, kt)
            entry: dict[str, Any] = {"columns": cols}
            fr = _date_freshness(cursor, kt, cols)
            if fr:
                entry["freshness"] = fr
            report["key_table_columns"][kt] = entry

        log.info("Fetching foreign key map...")
        report["foreign_keys"] = _foreign_keys(cursor)

    conn.close()

    # Stdout summary.
    _print_summary(report)

    # JSON report.
    out_path = args.output or Path(
        f"/tmp/vista_introspection_{report['server']['current_database']}.json"
    )
    out_path.write_text(json.dumps(report, indent=2, default=_json_default))
    print(f"\n  Full JSON report : {out_path}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
