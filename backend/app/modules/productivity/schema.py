"""Pydantic response models for the productivity module.

Reads from two parallel marts:
  - mart_productivity_labor      (per-phase labor hours)
  - mart_productivity_equipment  (per-phase equipment hours)

Both marts share the (tenant_id, job_label, phase_label) PK shape.
A single phase can have a row in either, both, or neither table.

Job/phase IDs in URLs are *stripped* — leading whitespace and internal
whitespace are collapsed. The mart stores Vista's raw labels (e.g.
" 2321. - CUWCD Santaquin Reach"), so the service layer does the
normalization in one place (_strip_job_key / _strip_phase_key).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums                                                                       #
# --------------------------------------------------------------------------- #


class ResourceKind(str, Enum):
    """Which mart a row was sourced from."""

    LABOR = "labor"
    EQUIPMENT = "equipment"


class PhaseStatus(str, Enum):
    """Per-phase health classification.

    Priority order (worst first): OVER_BUDGET > BEHIND_PACE > ON_TRACK > COMPLETE.
    UNKNOWN is reserved for rows missing the inputs needed to classify
    (typically zero estimated hours).

    OVER_BUDGET     actual_hours > est_hours and not yet complete.
    BEHIND_PACE     incomplete; pct_used outpaces pct_complete by more
                    than ``pace_band_pct``.
    ON_TRACK        incomplete; pct_used within band of pct_complete or
                    burning hours more slowly than progress.
    COMPLETE        pct_complete >= 1.0 — no further attention needed.
    UNKNOWN         missing or zero estimate.
    """

    OVER_BUDGET = "over_budget"
    BEHIND_PACE = "behind_pace"
    ON_TRACK = "on_track"
    COMPLETE = "complete"
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------- #
# Phase / job detail                                                          #
# --------------------------------------------------------------------------- #


class PhasePerf(BaseModel):
    """One resource-kind slice of a single phase.

    A phase's labor and equipment performance are tracked separately because
    they answer different questions: labor hours = crew-hours; equipment
    hours = machine operating hours. They diverge in real life (an excavator
    can run all day with no operator on payroll if it's idling, etc.).
    """

    resource_kind: ResourceKind
    actual_hours: float | None = None
    est_hours: float | None = None
    variance_hours: float | None = Field(
        None,
        description="est - actual, signed. Negative = over budget.",
    )
    percent_used: float | None = Field(
        None,
        description="actual / est. >1.0 means over budget on hours.",
    )
    percent_complete: float | None = Field(
        None,
        description="0.0–1.0 (may exceed 1.0 in edge cases).",
    )
    units_complete: float | None = None
    actual_units: float | None = None
    budget_hours: float | None = Field(
        None,
        description="Workbook-derived: est_hours * percent_complete.",
    )
    projected_hours: float | None = Field(
        None,
        description="PM-entered projection, falls back to calculated.",
    )
    schedule_performance_index: float | None = Field(
        None,
        description=(
            "percent_complete / percent_used. >1.0 ahead, <1.0 behind. "
            "None when percent_used is missing or zero."
        ),
    )
    status: PhaseStatus = PhaseStatus.UNKNOWN


class JobPhaseRow(BaseModel):
    """One phase row, with labor + equipment sides flattened together.

    The job detail endpoint returns one of these per phase (the union of
    labor.phase_label and equipment.phase_label for a given job).
    """

    phase_id: str = Field(
        ...,
        description="Stripped phase label (used in any future drill URL).",
    )
    phase: str = Field(..., description="Human-readable phase label.")
    project_end_date: datetime | None = None

    labor: PhasePerf | None = None
    equipment: PhasePerf | None = None

    # Worst-case status across both kinds — useful for sorting.
    worst_status: PhaseStatus = PhaseStatus.UNKNOWN


class JobHoursRollup(BaseModel):
    """Aggregate hours summed across all phases of a single job."""

    actual_hours: float
    est_hours: float
    variance_hours: float = Field(
        ..., description="est - actual. Negative = over budget."
    )
    percent_used: float | None = Field(
        None, description="actual / est. None when est == 0."
    )


class JobProductivityDetail(BaseModel):
    """Detail view for one job: phase grid + per-resource rollups."""

    id: str = Field(..., description="Stripped job key (URL form).")
    job: str = Field(..., description="Stripped job label (display form).")

    project_end_date: datetime | None = Field(
        None,
        description="Latest end_date observed across this job's phases.",
    )

    phases: list[JobPhaseRow]

    labor_rollup: JobHoursRollup | None = None
    equipment_rollup: JobHoursRollup | None = None

    # Phase counts by worst_status.
    phases_complete: int
    phases_on_track: int
    phases_behind_pace: int
    phases_over_budget: int
    phases_unknown: int


# --------------------------------------------------------------------------- #
# Summary (KPI tiles)                                                         #
# --------------------------------------------------------------------------- #


class ResourceTotals(BaseModel):
    """Totals for one resource_kind across all jobs/phases."""

    resource_kind: ResourceKind
    phases: int
    actual_hours: float
    est_hours: float
    percent_used: float | None = Field(
        None, description="Sum(actual) / sum(est). None when est == 0."
    )
    avg_percent_complete: float = Field(
        ...,
        description=(
            "Mean percent_complete across phases that have a value "
            "(0.0–1.0+)."
        ),
    )


class ProductivitySummary(BaseModel):
    """KPI tiles at the top of the Productivity screen."""

    total_jobs: int = Field(
        ..., description="Distinct jobs across labor + equipment marts."
    )
    total_phases: int = Field(
        ..., description="Distinct (job, phase) pairs across both marts."
    )

    labor_totals: ResourceTotals
    equipment_totals: ResourceTotals

    # Cross-resource totals (labor + equipment).
    combined_actual_hours: float
    combined_est_hours: float
    combined_percent_used: float | None = None

    # Phase-status counts (worst across labor/equipment per phase).
    phases_complete: int
    phases_on_track: int
    phases_behind_pace: int
    phases_over_budget: int
    phases_unknown: int

    # Phase-status counts as fractions (0–1.0) for chart-friendly display.
    pct_complete: float
    pct_on_track: float
    pct_behind_pace: float
    pct_over_budget: float
    pct_unknown: float


# --------------------------------------------------------------------------- #
# Attention list                                                              #
# --------------------------------------------------------------------------- #


class AttentionRow(BaseModel):
    """One phase that needs PM attention.

    The same (job, phase) tuple may surface twice if both its labor AND
    equipment slices are problematic — different ``resource_kind`` rows
    differentiate them.
    """

    job_id: str
    job: str
    phase_id: str
    phase: str
    resource_kind: ResourceKind
    status: PhaseStatus

    actual_hours: float | None = None
    est_hours: float | None = None
    variance_hours: float | None = Field(
        None, description="est - actual. Negative = over budget."
    )
    percent_used: float | None = None
    percent_complete: float | None = None
    schedule_performance_index: float | None = None

    # Severity score so the UI can sort. Higher = worse.
    severity: float = Field(
        ...,
        description=(
            "OVER_BUDGET: |variance_hours| (always positive). "
            "BEHIND_PACE: actual_hours * (1 - SPI). 0 for everything else."
        ),
    )


class ProductivityAttention(BaseModel):
    as_of: datetime
    pace_band_pct: float = Field(
        ...,
        description=(
            "± band around pct_used == pct_complete classified as on track. "
            "Default 10."
        ),
    )
    total: int
    items: list[AttentionRow]
