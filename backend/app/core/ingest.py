"""
Generic Excel -> tenant DB ingest framework.

Each mart under backend/app/services/excel_marts/<module>/ declares an
IngestJob and registers it via register_job(). The framework:

    1. Reads the Excel file via pandas (openpyxl engine)
    2. Renames columns per column_map (source_header -> snake_case)
    3. Coerces types per type_map (errors='coerce' -> NaN, row survives)
    4. Drops rows where any dedupe_key is null after coercion
    5. Injects tenant_id when tenant_scoped=True (default)
    6. Dialect-portable UPSERT on dedupe_keys (Postgres + SQLite)
    7. Writes an ingest_log row capturing metrics + errors

Run:
    python -m app.core.ingest --tenant vancon --all
    python -m app.core.ingest --tenant vancon --job equipment.utilization

Sync-only. Pandas + bulk UPSERTs don't benefit from asyncio, and this
matches how app.core.seed runs as a batch job.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pandas as pd
from sqlalchemy import Engine, MetaData, Table, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.ingest_log import IngestLog
from app.models.tenant import Tenant

log = logging.getLogger("fieldbridge.ingest")


# Sentinel column used when a mart has no natural key. See
# data_mapping.md § "Dedupe key conventions" — row-hash is the fallback.
ROW_HASH_COL = "_row_hash"


# --------------------------------------------------------------------------- #
# Public types                                                                #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class IngestJob:
    """Declarative description of one Excel -> mart ingest.

    Jobs are pure data. Services under excel_marts/<module>/ingest.py create
    an IngestJob and pass it to register_job().
    """

    name: str                               # stable identifier for logs/CLI
    source_file: str | Path                 # abs path OR relative to data_dir
    target_table: str                       # existing SQL table name
    column_map: dict[str, str]              # {excel_header: snake_case_col}
    type_map: dict[str, type]               # {snake_case_col: python_type}
    dedupe_keys: list[str]                  # snake_case col names (post-rename)
    sheet_name: str | int | None = 0        # forwarded to pandas.read_excel
    skiprows: int = 0                       # forwarded to pandas.read_excel
    tenant_scoped: bool = True              # inject tenant_id column?


@dataclass
class IngestResult:
    job_name: str
    status: Literal["ok", "error", "partial"]
    rows_read: int = 0
    rows_written: int = 0
    rows_skipped: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0


# --------------------------------------------------------------------------- #
# Registry                                                                    #
# --------------------------------------------------------------------------- #

_REGISTRY: dict[str, IngestJob] = {}


def register_job(job: IngestJob) -> IngestJob:
    """Add a job to the global registry. Duplicate names raise."""
    if job.name in _REGISTRY:
        raise ValueError(f"Ingest job already registered: {job.name}")
    _REGISTRY[job.name] = job
    return job


def get_registry() -> dict[str, IngestJob]:
    """Copy of the current registry."""
    return dict(_REGISTRY)


def clear_registry() -> None:
    """Reset the registry. Intended for tests."""
    _REGISTRY.clear()


# --------------------------------------------------------------------------- #
# Engine                                                                      #
# --------------------------------------------------------------------------- #


def _sync_url(async_url: str) -> str:
    """Normalize the app's async DB URL to a sync driver for pandas/SA Core."""
    u = async_url.replace("+asyncpg", "").replace("+aiosqlite", "")
    # asyncpg URLs use postgresql://; psycopg2 can consume the same URL.
    return u


def _engine(database_url: str | None = None) -> Engine:
    url = database_url or _sync_url(settings.database_url)
    return create_engine(url, pool_pre_ping=True, future=True)


def _default_data_dir() -> Path:
    # backend/app/core/ingest.py -> parents[3] = fieldbridge/
    return Path(__file__).resolve().parents[3] / "data" / "vista_data"


# --------------------------------------------------------------------------- #
# Core ingest                                                                 #
# --------------------------------------------------------------------------- #


def run_ingest(
    job: IngestJob,
    tenant_id: str,
    *,
    database_url: str | None = None,
    data_dir: Path | None = None,
) -> IngestResult:
    """Execute one ingest job synchronously.

    All failures are captured onto IngestResult; this function does not raise
    for data errors. It does raise for programmer errors (e.g. bad SQL).
    """
    started = time.time()
    started_at = datetime.now(timezone.utc)
    result = IngestResult(job_name=job.name, status="ok")

    source = _resolve_source_path(job.source_file, data_dir)
    engine = _engine(database_url)
    SessionLocal = sessionmaker(engine, expire_on_commit=False)

    try:
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {source}")

        df = pd.read_excel(
            source,
            sheet_name=job.sheet_name,
            skiprows=job.skiprows,
            engine=_engine_for_excel(source),
        )
        result.rows_read = len(df)

        df = _rename_columns(df, job.column_map, result)
        df, coerce_errs = _coerce_types(df, job.type_map)
        result.errors.extend(coerce_errs)

        if ROW_HASH_COL in job.dedupe_keys:
            df = _add_row_hash(df, job)
            result.errors.append(
                f"WARN dedupe_strategy=row_hash job={job.name} — "
                "no natural key; verify data quality and promote"
            )

        df, skipped = _drop_null_dedupe(df, job.dedupe_keys)
        result.rows_skipped = skipped

        if job.tenant_scoped:
            df["tenant_id"] = tenant_id

        result.rows_written = _upsert(
            engine, job.target_table, df, job.dedupe_keys
        )

        if result.errors:
            result.status = "partial"

    except Exception as exc:  # noqa: BLE001
        log.exception("Ingest job %s failed", job.name)
        result.status = "error"
        result.errors.append(f"{type(exc).__name__}: {exc}")

    result.duration_ms = int((time.time() - started) * 1000)

    # Always log, even on failure.
    try:
        with SessionLocal() as s:
            _log_run(s, tenant_id, job, source, result, started_at)
    except Exception as log_exc:  # noqa: BLE001
        log.error("Failed to write ingest_log: %s", log_exc)

    return result


def run_all(
    tenant_id: str,
    *,
    job_names: list[str] | None = None,
    database_url: str | None = None,
    data_dir: Path | None = None,
) -> list[IngestResult]:
    """Run every registered job (or the named subset) for a tenant."""
    jobs = list(_REGISTRY.values())
    if job_names:
        wanted = set(job_names)
        selected = [j for j in jobs if j.name in wanted]
        missing = wanted - {j.name for j in selected}
        if missing:
            raise KeyError(f"Unknown ingest job(s): {sorted(missing)}")
        jobs = selected
    return [
        run_ingest(j, tenant_id, database_url=database_url, data_dir=data_dir)
        for j in jobs
    ]


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _resolve_source_path(raw: str | Path, data_dir: Path | None) -> Path:
    p = Path(raw)
    if p.is_absolute():
        return p
    return (data_dir or _default_data_dir()) / p


# Map of file extension → pandas read_excel engine. Pandas can auto-pick,
# but stale openpyxl-only installs choke silently on .xlsb, so we force the
# right engine and surface a clear error if the format is unsupported.
_EXCEL_ENGINES: dict[str, str] = {
    ".xlsx": "openpyxl",
    ".xlsm": "openpyxl",
    ".xlsb": "pyxlsb",      # binary Excel — much smaller than .xlsx
    ".xls":  "xlrd",        # legacy; not currently in requirements.txt
    ".ods":  "odf",         # ditto
}


def _engine_for_excel(source: Path) -> str:
    ext = source.suffix.lower()
    try:
        return _EXCEL_ENGINES[ext]
    except KeyError:
        raise ValueError(
            f"Unsupported Excel format {ext!r} for {source.name}. "
            f"Supported: {sorted(_EXCEL_ENGINES)}"
        )


def _rename_columns(
    df: pd.DataFrame, column_map: dict[str, str], result: IngestResult
) -> pd.DataFrame:
    missing = [c for c in column_map if c not in df.columns]
    for c in missing:
        result.errors.append(f"missing source column: {c!r}")
    rename = {src: tgt for src, tgt in column_map.items() if src in df.columns}
    return df.rename(columns=rename)


def _coerce_types(
    df: pd.DataFrame, type_map: dict[str, type]
) -> tuple[pd.DataFrame, list[str]]:
    errors: list[str] = []
    for col, typ in type_map.items():
        if col not in df.columns:
            errors.append(f"type_map refers to missing column: {col!r}")
            continue
        before = int(df[col].notna().sum())
        if typ is int:
            # Two-step cast: numeric coercion → Float64 (nullable) → Int64.
            # Going direct to Int64 fails on object-dtype columns where
            # every value was unparseable (all-NaN object arrays can't be
            # safely cast). Float64 is an unambiguous intermediate.
            df[col] = (
                pd.to_numeric(df[col], errors="coerce")
                .astype("Float64")
                .astype("Int64")
            )
        elif typ is float:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        elif typ is bool:
            df[col] = df[col].astype("boolean")
        elif typ is datetime:
            df[col] = pd.to_datetime(df[col], errors="coerce")
        elif typ is str:
            df[col] = df[col].astype("string")
        else:
            errors.append(f"{col}: unsupported type {typ!r} in type_map")
            continue
        after = int(df[col].notna().sum())
        diff = before - after
        if diff > 0:
            errors.append(
                f"{col}: {diff} value(s) failed {typ.__name__} coercion"
            )
    return df, errors


def _add_row_hash(df: pd.DataFrame, job: IngestJob) -> pd.DataFrame:
    """Synthesize a deterministic per-row hash from all payload columns.

    Used when a mart has no natural key. The hash is stable across runs as
    long as the source column order + values don't change, so re-ingest of
    the same file UPSERTs rather than duplicates.
    """
    payload_cols = [
        c for c in df.columns
        if c != ROW_HASH_COL and c != "tenant_id"
    ]

    def _hash_row(row: pd.Series) -> str:
        parts = []
        for c in payload_cols:
            v = row[c]
            if pd.isna(v):
                parts.append(f"{c}=\x00")
            else:
                parts.append(f"{c}={v!r}")
        return hashlib.md5("\x1f".join(parts).encode("utf-8")).hexdigest()

    df[ROW_HASH_COL] = df.apply(_hash_row, axis=1)
    return df


def _drop_null_dedupe(
    df: pd.DataFrame, keys: list[str]
) -> tuple[pd.DataFrame, int]:
    """Drop rows that can't be upserted: nulls in dedupe keys + intra-batch
    duplicates on those same keys.

    Postgres's `INSERT ... ON CONFLICT DO UPDATE` raises CardinalityViolation
    when the same batch carries two rows with identical constraint columns —
    it can't pick which one to apply. Source Excel exports routinely contain
    such duplicates (manual data entry, repeated barcodes, paired bid lines,
    etc.), so we collapse them to last-wins here. `skipped` reports the total
    of both null-drop and dedupe-drop, since both are "not written".
    """
    present = [k for k in keys if k in df.columns]
    if not present:
        return df, 0
    null_mask = df[present].isna().any(axis=1)
    no_nulls = df.loc[~null_mask].copy()
    deduped = no_nulls.drop_duplicates(subset=present, keep="last")
    skipped = int(null_mask.sum()) + (len(no_nulls) - len(deduped))
    return deduped, skipped


# Driver-level parameter caps. We chunk rows so (rows × cols) stays under
# each driver's hard limit. SQLite's compile-time default is 32766 on
# recent builds (was 999 pre-3.32); psycopg2/asyncpg cap parameters at
# ~65535 per statement. Keep a margin for on-conflict UPDATE clauses which
# reference `excluded.col` and count toward the limit.
_PARAM_CAPS = {"sqlite": 20000, "postgresql": 40000}


def _upsert(
    engine: Engine,
    table_name: str,
    df: pd.DataFrame,
    dedupe_keys: list[str],
) -> int:
    if df.empty:
        return 0

    meta = MetaData()
    table = Table(table_name, meta, autoload_with=engine)

    # NaN / pd.NA -> None for drivers that dislike numpy NaN
    rows = (
        df.astype(object).where(pd.notna(df), None).to_dict(orient="records")
    )

    dialect = engine.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as _insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as _insert
    else:
        raise NotImplementedError(
            f"UPSERT not implemented for dialect: {dialect}"
        )

    cap = _PARAM_CAPS.get(dialect, 20000)
    cols_per_row = max(1, len(table.columns))
    chunk_size = max(1, cap // cols_per_row)

    update_cols_names = [
        c.name for c in table.columns if c.name not in dedupe_keys
    ]

    total_written = 0
    with engine.begin() as conn:
        for start in range(0, len(rows), chunk_size):
            chunk = rows[start:start + chunk_size]
            stmt = _insert(table).values(chunk)
            if update_cols_names:
                stmt = stmt.on_conflict_do_update(
                    index_elements=dedupe_keys,
                    set_={n: stmt.excluded[n] for n in update_cols_names},
                )
            else:
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=dedupe_keys
                )
            conn.execute(stmt)
            total_written += len(chunk)
    return total_written


def _log_run(
    session: Session,
    tenant_id: str,
    job: IngestJob,
    source: Path,
    result: IngestResult,
    started_at: datetime,
) -> None:
    rec = IngestLog(
        tenant_id=tenant_id,
        job_name=job.name,
        source_file=str(source),
        target_table=job.target_table,
        status=result.status,
        rows_read=result.rows_read,
        rows_written=result.rows_written,
        rows_skipped=result.rows_skipped,
        errors=json.dumps(result.errors[:50]),
        duration_ms=result.duration_ms,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
    )
    session.add(rec)
    session.commit()


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run Excel ingest jobs.")
    parser.add_argument(
        "--tenant", required=True, help="tenant slug, e.g. vancon"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--all", action="store_true", help="run every registered job"
    )
    group.add_argument(
        "--job", action="append",
        help="run a named job (may be repeated)",
    )
    parser.add_argument(
        "--data-dir", type=Path, default=None,
        help="override the default vista_data dir",
    )
    parser.add_argument(
        "--database-url", default=None,
        help="override settings.database_url (expects a sync URL)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    # Import mart packages so their @register_job calls populate _REGISTRY
    # before --all / --job runs. No-op if already imported.
    try:
        import app.services.excel_marts  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not import excel_marts registry: %s", exc)

    database_url = args.database_url
    engine = _engine(database_url)
    SessionLocal = sessionmaker(engine)
    with SessionLocal() as s:
        tenant = s.execute(
            select(Tenant).where(Tenant.slug == args.tenant)
        ).scalar_one_or_none()
        if not tenant:
            log.error("No tenant with slug %r", args.tenant)
            return 2
        tenant_id = tenant.id

    if not _REGISTRY:
        log.warning(
            "No ingest jobs registered. Import the mart services that declare "
            "jobs before invoking --all (see backend/app/services/excel_marts)."
        )
        return 0

    jobs_to_run = None if args.all else args.job
    results = run_all(
        tenant_id,
        job_names=jobs_to_run,
        data_dir=args.data_dir,
        database_url=database_url,
    )

    for r in results:
        log.info(
            "[%s] %s  read=%d written=%d skipped=%d dur=%dms errs=%d",
            r.status, r.job_name, r.rows_read, r.rows_written,
            r.rows_skipped, r.duration_ms, len(r.errors),
        )
        for e in r.errors:
            log.info("    %s", e)

    return 0 if all(r.status != "error" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
