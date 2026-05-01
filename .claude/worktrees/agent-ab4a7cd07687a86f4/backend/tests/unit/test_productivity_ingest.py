"""
Tests for the productivity mart (labor + equipment).

These cover the productivity-specific concerns on top of the framework
tests in test_ingest.py:

    - Two independent target tables, populated by two independent jobs.
    - Same (job, phase) tuple can land in both tables without conflict
      (they share a key space concept but live in distinct tables).
    - Null Job / Phase rows are dropped (real workbooks have one such row).
    - Idempotent re-run.
    - The real source files (if present) ingest cleanly — this smoke test
      catches the blank-named column at the source's index 14 (' ') and
      any type/coercion drift if VanCon's webapp export shape changes.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

# Importing the productivity module triggers register_job() side effects
# AND adds the two Tables to Base.metadata, so the engine fixture's
# create_all() picks them up.
from app.services.excel_marts.productivity import (  # noqa: F401
    EQUIPMENT_TABLE_NAME,
    LABOR_TABLE_NAME,
    equipment_job,
    equipment_table,
    labor_job,
    labor_table,
)
from app.core.ingest import IngestJob, run_ingest


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _real_data_dir() -> Path:
    # tests/unit/test_productivity_ingest.py -> parents[3] = fieldbridge/
    return Path(__file__).resolve().parents[3] / "data" / "vista_data"


def _job_with_source(j: IngestJob, source: Path) -> IngestJob:
    """Clone a registered IngestJob with a different source_file path.

    IngestJob is frozen, so we can't mutate; a new instance carries the
    same column_map/type_map/dedupe_keys/sheet_name into run_ingest.
    """
    return IngestJob(
        name=j.name,
        source_file=str(source),
        target_table=j.target_table,
        column_map=j.column_map,
        type_map=j.type_map,
        dedupe_keys=j.dedupe_keys,
        sheet_name=j.sheet_name,
        skiprows=j.skiprows,
        tenant_scoped=j.tenant_scoped,
    )


def _sample_frame(jobs: list[tuple[str, str]]) -> pd.DataFrame:
    """Build a Productivity Summary-shaped DataFrame for tests.

    Columns mirror the real workbook so column_map.get(col) works as
    expected. The blank column (' ') is included to match the real shape.
    """
    rows = []
    for job, phase in jobs:
        rows.append(
            {
                "Job": job,
                "Phase": phase,
                "Actual Hours": 100.0,
                "Est Hours": 120.0,
                "Variance": 20.0,
                "Percent Used": 0.833,
                "Units Complete": 50.0,
                "Actual Units": 48.0,
                "% Complete": 0.50,
                "Calculated Budget Hrs": 60.0,
                "Calculated Budget Hrs-Actual": -40.0,
                "Calculated Projected Hours": 200.0,
                "Projected Hours": 210.0,
                "Efficiency Rate": 0.96,
                " ": None,                   # the blank-named column
                "End Date": pd.Timestamp("2026-12-31"),
            }
        )
    return pd.DataFrame(rows)


def _write_xlsx(dir_: Path, name: str, df: pd.DataFrame) -> Path:
    path = dir_ / name
    # Match the real workbook: sheet name is "Productivity Summary"
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="Productivity Summary", index=False)
    return path


# --------------------------------------------------------------------------- #
# Both tables exist after metadata create_all                                 #
# --------------------------------------------------------------------------- #


def test_both_tables_created(engine):
    """Confirm engine fixture's create_all() built both productivity tables."""
    with engine.connect() as c:
        # SQLite: sqlite_master has the table list.
        names = {
            row[0] for row in c.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name LIKE 'mart_productivity_%'"
                )
            ).all()
        }
    assert names == {LABOR_TABLE_NAME, EQUIPMENT_TABLE_NAME}


# --------------------------------------------------------------------------- #
# Labor job populates only the labor table                                    #
# --------------------------------------------------------------------------- #


def test_labor_job_populates_labor_table_only(
    sqlite_db, engine, tenant_id, tmp_path
):
    src = _write_xlsx(
        tmp_path,
        "Productivity Summary_labor.xlsx",
        _sample_frame([("J100", "P10"), ("J100", "P20")]),
    )
    result = run_ingest(
        _job_with_source(labor_job, src),
        tenant_id,
        database_url=sqlite_db,
    )

    assert result.status == "ok", result.errors
    assert result.rows_read == 2
    assert result.rows_written == 2
    assert result.rows_skipped == 0

    with engine.connect() as c:
        labor_count = c.execute(
            text(f"SELECT COUNT(*) FROM {LABOR_TABLE_NAME}")
        ).scalar_one()
        equipment_count = c.execute(
            text(f"SELECT COUNT(*) FROM {EQUIPMENT_TABLE_NAME}")
        ).scalar_one()
        sample = c.execute(
            text(
                f"SELECT job_label, phase_label, actual_hours, est_hours, "
                f"percent_complete, project_end_date "
                f"FROM {LABOR_TABLE_NAME} WHERE phase_label = 'P10'"
            )
        ).one()

    assert labor_count == 2
    assert equipment_count == 0          # equipment table untouched
    assert sample[0] == "J100"
    assert sample[1] == "P10"
    assert sample[2] == 100.0
    assert sample[3] == 120.0
    assert sample[4] == 0.50


# --------------------------------------------------------------------------- #
# Equipment job populates only the equipment table — independent key space   #
# --------------------------------------------------------------------------- #


def test_equipment_job_independent_of_labor(
    sqlite_db, engine, tenant_id, tmp_path
):
    """The same (job, phase) tuple can exist in both tables — they're
    independent PKs. This proves the two-table design supports the real-
    world case where a phase has both labor *and* equipment hours."""
    pairs = [("J200", "P30"), ("J200", "P40")]

    labor_src = _write_xlsx(
        tmp_path, "Productivity Summary_labor.xlsx", _sample_frame(pairs)
    )
    equip_src = _write_xlsx(
        tmp_path, "Productivity Summary_equipment.xlsx", _sample_frame(pairs)
    )

    r_labor = run_ingest(
        _job_with_source(labor_job, labor_src),
        tenant_id, database_url=sqlite_db,
    )
    r_equip = run_ingest(
        _job_with_source(equipment_job, equip_src),
        tenant_id, database_url=sqlite_db,
    )

    assert r_labor.status == "ok", r_labor.errors
    assert r_equip.status == "ok", r_equip.errors

    with engine.connect() as c:
        labor_count = c.execute(
            text(f"SELECT COUNT(*) FROM {LABOR_TABLE_NAME}")
        ).scalar_one()
        equipment_count = c.execute(
            text(f"SELECT COUNT(*) FROM {EQUIPMENT_TABLE_NAME}")
        ).scalar_one()

    assert labor_count == 2
    assert equipment_count == 2


# --------------------------------------------------------------------------- #
# Null job / phase rows are dropped                                           #
# --------------------------------------------------------------------------- #


def test_null_job_or_phase_rows_dropped(
    sqlite_db, engine, tenant_id, tmp_path
):
    """Real workbook has one row with NaN Job and Phase — it must drop.

    A fully-NaN Excel row gets stripped by pandas at read time, so we
    seed the dedupe-key fields as None but leave other fields populated.
    That mirrors the failure mode in the real export: a footer/total row
    with hours but no job key.
    """
    df = _sample_frame([("J300", "P50")])
    # Add a row whose Job/Phase are NaN but with hour values present, so
    # pandas keeps it on read; _drop_null_dedupe should then strip it.
    df = pd.concat(
        [
            df,
            pd.DataFrame(
                [
                    {
                        "Job": None, "Phase": None,
                        "Actual Hours": 5.0, "Est Hours": 6.0,
                        "Variance": 1.0, "Percent Used": 0.83,
                        "Units Complete": 0.0, "Actual Units": 0.0,
                        "% Complete": 0.0,
                        "Calculated Budget Hrs": 0.0,
                        "Calculated Budget Hrs-Actual": 0.0,
                        "Calculated Projected Hours": 0.0,
                        "Projected Hours": 0.0,
                        "Efficiency Rate": 0.0,
                        " ": None,
                        "End Date": pd.Timestamp("2026-01-01"),
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    src = _write_xlsx(tmp_path, "Productivity Summary_labor.xlsx", df)

    result = run_ingest(
        _job_with_source(labor_job, src),
        tenant_id, database_url=sqlite_db,
    )

    assert result.rows_read == 2
    assert result.rows_skipped == 1
    assert result.rows_written == 1


# --------------------------------------------------------------------------- #
# Idempotent re-run                                                           #
# --------------------------------------------------------------------------- #


def test_idempotent_rerun_upserts(
    sqlite_db, engine, tenant_id, tmp_path
):
    src = _write_xlsx(
        tmp_path,
        "Productivity Summary_labor.xlsx",
        _sample_frame([("J400", "P60"), ("J400", "P70")]),
    )
    run_ingest(
        _job_with_source(labor_job, src),
        tenant_id, database_url=sqlite_db,
    )

    # Tweak the source numbers, write a second file, ingest again.
    df2 = _sample_frame([("J400", "P60"), ("J400", "P70")])
    df2.loc[:, "Actual Hours"] = 999.0
    src2 = _write_xlsx(tmp_path, "Productivity Summary_labor_v2.xlsx", df2)

    run_ingest(
        _job_with_source(labor_job, src2),
        tenant_id, database_url=sqlite_db,
    )

    with engine.connect() as c:
        total = c.execute(
            text(f"SELECT COUNT(*) FROM {LABOR_TABLE_NAME}")
        ).scalar_one()
        rows = c.execute(
            text(
                f"SELECT phase_label, actual_hours FROM {LABOR_TABLE_NAME} "
                f"ORDER BY phase_label"
            )
        ).all()

    assert total == 2
    assert rows == [("P60", 999.0), ("P70", 999.0)]


# --------------------------------------------------------------------------- #
# Real source files smoke test (skip if missing)                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "job",
    [labor_job, equipment_job],
    ids=lambda j: j.name,
)
def test_real_source_file_ingests(sqlite_db, engine, tenant_id, job):
    """Smoke test against the real VanCon webapp exports.

    Skipped when source files aren't checked in (CI-safe). When the files
    are present this catches:
      - column shape drift in the export
      - the blank-named column at index 14 not breaking SA's insert
      - type coercion failures
    """
    src = _real_data_dir() / job.source_file
    if not src.exists():
        pytest.skip(f"Real source file not present: {src}")

    result = run_ingest(
        job,
        tenant_id,
        database_url=sqlite_db,
        data_dir=_real_data_dir(),
    )

    assert result.status in ("ok", "partial"), result.errors
    assert result.rows_read > 0
    assert result.rows_written > 0
    # Real files have ~2009 rows; allow drift but flag obvious truncation.
    assert result.rows_written >= result.rows_read - 50

    with engine.connect() as c:
        count = c.execute(
            text(f"SELECT COUNT(*) FROM {job.target_table}")
        ).scalar_one()
    assert count == result.rows_written
