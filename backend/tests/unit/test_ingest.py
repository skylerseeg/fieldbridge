"""
Framework-level tests for app.core.ingest.

Covers: happy path, missing file, type coercion failure, partial dedupe,
idempotent re-run (UPSERT semantics), ingest_log write.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

from app.core.ingest import IngestJob, clear_registry, run_ingest


@pytest.fixture(autouse=True)
def _reset_registry():
    """Keep the registry clean between tests."""
    clear_registry()
    yield
    clear_registry()


def _write_xlsx(dir_: Path, name: str, df: pd.DataFrame) -> Path:
    p = dir_ / name
    df.to_excel(p, index=False)
    return p


def _make_job(source: Path | str, **overrides) -> IngestJob:
    defaults = dict(
        name="test.sample",
        source_file=str(source),
        target_table="mart_test_sample",
        column_map={"ID": "id", "Description": "description", "Amount": "amount"},
        type_map={"amount": float},
        dedupe_keys=["tenant_id", "id"],
    )
    defaults.update(overrides)
    return IngestJob(**defaults)


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #


def test_happy_path(sqlite_db, engine, tenant_id, mart_table, tmp_path):
    src = _write_xlsx(
        tmp_path,
        "sample.xlsx",
        pd.DataFrame(
            {
                "ID": ["A1", "A2", "A3"],
                "Description": ["alpha", "beta", "gamma"],
                "Amount": [10.5, 20, 30.1],
            }
        ),
    )
    result = run_ingest(_make_job(src), tenant_id, database_url=sqlite_db)

    assert result.status == "ok"
    assert result.rows_read == 3
    assert result.rows_written == 3
    assert result.rows_skipped == 0
    assert result.errors == []
    assert result.duration_ms >= 0

    with engine.connect() as c:
        count = c.execute(
            text("SELECT COUNT(*) FROM mart_test_sample")
        ).scalar_one()
        sample = c.execute(
            text(
                "SELECT id, description, amount "
                "FROM mart_test_sample WHERE id = 'A1'"
            )
        ).one()

    assert count == 3
    assert sample == ("A1", "alpha", 10.5)


# --------------------------------------------------------------------------- #
# Missing file                                                                #
# --------------------------------------------------------------------------- #


def test_missing_file(sqlite_db, engine, tenant_id, mart_table):
    job = _make_job(
        "/definitely/does/not/exist/nowhere.xlsx", name="test.missing"
    )
    result = run_ingest(job, tenant_id, database_url=sqlite_db)

    assert result.status == "error"
    assert result.rows_read == 0
    assert result.rows_written == 0
    assert any("FileNotFoundError" in e for e in result.errors)

    # The run still got logged.
    with engine.connect() as c:
        logged = c.execute(
            text(
                "SELECT job_name, status, rows_written FROM ingest_log "
                "WHERE job_name = 'test.missing'"
            )
        ).one()
    assert logged == ("test.missing", "error", 0)


# --------------------------------------------------------------------------- #
# Type coercion failure                                                       #
# --------------------------------------------------------------------------- #


def test_type_coercion_failure_keeps_row_but_nulls_cell(
    sqlite_db, engine, tenant_id, mart_table, tmp_path
):
    """
    One 'amount' value can't be coerced to float. The row still lands
    (dedupe keys are fine) but the bad cell becomes NULL and the
    IngestResult is marked partial with a descriptive error.
    """
    src = _write_xlsx(
        tmp_path,
        "types.xlsx",
        pd.DataFrame(
            {
                "ID": ["A1", "A2", "A3"],
                "Description": ["x", "y", "z"],
                "Amount": ["10.5", "not-a-number", "30"],
            }
        ),
    )
    result = run_ingest(
        _make_job(src, name="test.types"), tenant_id, database_url=sqlite_db
    )

    assert result.status == "partial"
    assert result.rows_read == 3
    assert result.rows_written == 3
    assert any(
        "amount" in e and "failed float coercion" in e for e in result.errors
    )

    with engine.connect() as c:
        bad = c.execute(
            text("SELECT amount FROM mart_test_sample WHERE id = 'A2'")
        ).scalar_one()
    assert bad is None


# --------------------------------------------------------------------------- #
# Partial dedupe (null dedupe key rows)                                       #
# --------------------------------------------------------------------------- #


def test_partial_dedupe_drops_null_keys(
    sqlite_db, engine, tenant_id, mart_table, tmp_path
):
    src = _write_xlsx(
        tmp_path,
        "dedupe.xlsx",
        pd.DataFrame(
            {
                "ID": ["A1", None, "A3", None, "A5"],
                "Description": ["a", "b", "c", "d", "e"],
                "Amount": [1, 2, 3, 4, 5],
            }
        ),
    )
    result = run_ingest(
        _make_job(src, name="test.dedupe"),
        tenant_id,
        database_url=sqlite_db,
    )

    assert result.status == "ok"
    assert result.rows_read == 5
    assert result.rows_skipped == 2
    assert result.rows_written == 3

    with engine.connect() as c:
        count = c.execute(
            text("SELECT COUNT(*) FROM mart_test_sample")
        ).scalar_one()
    assert count == 3


# --------------------------------------------------------------------------- #
# Idempotent re-run: UPSERT, not duplicate                                    #
# --------------------------------------------------------------------------- #


def test_idempotent_rerun_updates_on_conflict(
    sqlite_db, engine, tenant_id, mart_table, tmp_path
):
    src1 = _write_xlsx(
        tmp_path,
        "round1.xlsx",
        pd.DataFrame(
            {
                "ID": ["A1", "A2"],
                "Description": ["v1", "v1"],
                "Amount": [1, 2],
            }
        ),
    )
    src2 = _write_xlsx(
        tmp_path,
        "round2.xlsx",
        pd.DataFrame(
            {
                "ID": ["A1", "A2"],
                "Description": ["v2", "v2"],
                "Amount": [11, 22],
            }
        ),
    )
    run_ingest(
        _make_job(src1, name="test.upsert"), tenant_id, database_url=sqlite_db
    )
    run_ingest(
        _make_job(src2, name="test.upsert"), tenant_id, database_url=sqlite_db
    )

    with engine.connect() as c:
        total = c.execute(
            text("SELECT COUNT(*) FROM mart_test_sample")
        ).scalar_one()
        rows = c.execute(
            text(
                "SELECT id, description, amount FROM mart_test_sample "
                "ORDER BY id"
            )
        ).all()

    assert total == 2
    assert rows == [("A1", "v2", 11.0), ("A2", "v2", 22.0)]

    # Two runs logged.
    with engine.connect() as c:
        log_count = c.execute(
            text(
                "SELECT COUNT(*) FROM ingest_log WHERE job_name = 'test.upsert'"
            )
        ).scalar_one()
    assert log_count == 2


# --------------------------------------------------------------------------- #
# ingest_log captures metrics                                                 #
# --------------------------------------------------------------------------- #


def test_row_hash_dedupe_writes_once_and_logs_warn(
    sqlite_db, engine, tenant_id, mart_row_hash_table, tmp_path
):
    """Mart with no natural key: _row_hash fallback dedupes re-runs and
    surfaces a WARN in ingest_log's errors payload."""
    src = _write_xlsx(
        tmp_path,
        "contacts.xlsx",
        pd.DataFrame(
            {
                "Name": ["Alice", "Bob", "Carol"],
                "Phone": ["555-1111", "555-2222", "555-3333"],
            }
        ),
    )
    job = IngestJob(
        name="test.row_hash",
        source_file=str(src),
        target_table="mart_test_row_hash",
        column_map={"Name": "name", "Phone": "phone"},
        type_map={"name": str, "phone": str},
        dedupe_keys=["tenant_id", "_row_hash"],
    )

    r1 = run_ingest(job, tenant_id, database_url=sqlite_db)
    r2 = run_ingest(job, tenant_id, database_url=sqlite_db)

    assert r1.status == "partial"          # WARN counts as a non-fatal error
    assert r1.rows_written == 3
    assert any("row_hash" in e for e in r1.errors)
    assert r2.rows_written == 3            # same hashes, upsert not insert

    with engine.connect() as c:
        count = c.execute(
            text("SELECT COUNT(*) FROM mart_test_row_hash")
        ).scalar_one()
    assert count == 3                      # no duplication across runs


def test_ingest_log_records_metrics(
    sqlite_db, engine, tenant_id, mart_table, tmp_path
):
    src = _write_xlsx(
        tmp_path,
        "log.xlsx",
        pd.DataFrame(
            {"ID": ["A1"], "Description": ["x"], "Amount": [42.0]}
        ),
    )
    run_ingest(
        _make_job(src, name="test.log"), tenant_id, database_url=sqlite_db
    )

    with engine.connect() as c:
        row = c.execute(
            text(
                "SELECT job_name, status, rows_read, rows_written, "
                "rows_skipped, target_table FROM ingest_log "
                "WHERE job_name = 'test.log'"
            )
        ).one()

    assert row == ("test.log", "ok", 1, 1, 0, "mart_test_sample")
