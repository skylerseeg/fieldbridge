"""Pydantic response models for the predictive_maintenance module.

Mirrors ``frontend/src/modules/predictive-maintenance/predictive-maintenance-api.ts``
1:1 — that file is the SPEC-FIRST contract this backend implements.
Keep these in sync when the TS file changes.

Two backing tables (``mart_predictive_maintenance`` +
``mart_predictive_maintenance_history``) are defined under
``app/services/excel_marts/predictive_maintenance/`` and registered on
``Base.metadata``. Phase 1 ships with empty tables — endpoints return
zeroed counts and empty lists until a writer is built.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums                                                                       #
# --------------------------------------------------------------------------- #


class RiskTier(str, Enum):
    """Combined likelihood + severity bucket from the agent."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class MaintStatus(str, Enum):
    """Workflow state of a prediction.

    Transitions (driven by the mutation endpoints):
        open -> acknowledged | scheduled | dismissed
        acknowledged -> scheduled | completed | dismissed
        scheduled -> completed | dismissed
        completed -> (terminal)
        dismissed -> (terminal)
    """

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    DISMISSED = "dismissed"


class MaintSource(str, Enum):
    """Where the prediction came from.

    Drives which date column matters: pm_overdue rows use ``pm_due_date``
    (calendar PM target), failure_prediction rows use
    ``predicted_failure_date`` (AI-derived).
    """

    PM_OVERDUE = "pm_overdue"
    FAILURE_PREDICTION = "failure_prediction"


class FailureMode(str, Enum):
    """Free-form failure category — six values today.

    ``other`` is the catch-all; widen the enum (and the TS counterpart)
    rather than ever introducing a seventh slug here.
    """

    ENGINE = "engine"
    HYDRAULIC = "hydraulic"
    ELECTRICAL = "electrical"
    DRIVETRAIN = "drivetrain"
    STRUCTURAL = "structural"
    OTHER = "other"


# --------------------------------------------------------------------------- #
# List                                                                        #
# --------------------------------------------------------------------------- #


class PredictionListRow(BaseModel):
    """One row in the paginated ``GET /list`` response."""

    id: str
    equipment_id: str
    equipment_label: str

    risk_tier: RiskTier
    status: MaintStatus
    source: MaintSource
    failure_mode: FailureMode

    predicted_failure_date: datetime | None = Field(
        None,
        description=(
            "Set only for ``failure_prediction`` rows. Days-until-due "
            "for these is computed off this column."
        ),
    )
    pm_due_date: datetime | None = Field(
        None,
        description=(
            "Set only for ``pm_overdue`` rows (calendar PM target). "
            "Days-until-due is computed off this column."
        ),
    )
    days_until_due: int | None = Field(
        None,
        description=(
            "Negative when overdue. Computed at read time from the "
            "matching date column for the row's ``source``. ``null`` "
            "when both date columns are NULL."
        ),
    )

    estimated_downtime_hours: float | None = None
    estimated_repair_cost: float | None = None

    recommended_action: str

    created_at: datetime
    updated_at: datetime
    scheduled_for: datetime | None = Field(
        None,
        description="Only set when ``status == 'scheduled'``.",
    )

    age_days: int = Field(
        ...,
        description=(
            "Days since ``created_at``. Bucketed by the insights endpoint "
            "into fresh / mature / stale."
        ),
    )


class PredictionListResponse(BaseModel):
    """Paged result for ``GET /list``."""

    total: int = Field(
        ...,
        description=(
            "Total rows matching the filters before pagination. Equal "
            "to ``items`` length on the last page."
        ),
    )
    page: int
    page_size: int
    sort_by: str
    sort_dir: str
    items: list[PredictionListRow]


# --------------------------------------------------------------------------- #
# Summary                                                                     #
# --------------------------------------------------------------------------- #


class PredictiveMaintenanceSummary(BaseModel):
    """KPI-strip rollup for the page header.

    "Open" means ``status == 'open'``; "lifetime" counts span every
    status. Kept flat (no nested ``by_*`` objects) to match the TS
    contract exactly.
    """

    total_predictions: int

    open_count: int
    acknowledged_count: int
    scheduled_count: int
    completed_count: int
    dismissed_count: int

    # Lifetime risk-tier counts (every status).
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int

    # Drilldowns on the open population only.
    open_critical_count: int
    open_overdue_count: int = Field(
        ...,
        description=(
            "Open predictions where ``days_until_due < 0`` — the "
            "page-header red-bar threshold."
        ),
    )

    pm_overdue_count: int = Field(
        ...,
        description="Open predictions sourced from calendar PM rules.",
    )
    failure_prediction_count: int = Field(
        ...,
        description="Open predictions sourced from the AI agent.",
    )

    total_estimated_exposure: float = Field(
        ...,
        description=(
            "Sum of ``estimated_repair_cost`` across open predictions. "
            "NULL costs treated as 0."
        ),
    )
    total_estimated_downtime_hours: float = Field(
        ...,
        description="Sum of ``estimated_downtime_hours`` across open.",
    )
    average_age_days: float | None = Field(
        None,
        description=(
            "Mean ``age_days`` across open predictions. ``null`` when "
            "no rows are open."
        ),
    )
    oldest_open_age_days: int | None = Field(
        None,
        description=(
            "Max ``age_days`` across open predictions. ``null`` when "
            "no rows are open."
        ),
    )

    distinct_equipment: int
    distinct_failure_modes: int


# --------------------------------------------------------------------------- #
# Insights                                                                    #
# --------------------------------------------------------------------------- #


class RiskTierBreakdown(BaseModel):
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0


class MaintStatusBreakdown(BaseModel):
    open: int = 0
    acknowledged: int = 0
    scheduled: int = 0
    completed: int = 0
    dismissed: int = 0


class MaintSourceBreakdown(BaseModel):
    pm_overdue: int = 0
    failure_prediction: int = 0


class FailureModeBreakdown(BaseModel):
    engine: int = 0
    hydraulic: int = 0
    electrical: int = 0
    drivetrain: int = 0
    structural: int = 0
    other: int = 0


class AgingBreakdown(BaseModel):
    """Age distribution of open predictions.

    Buckets:
        fresh  — age_days < 7
        mature — 7 <= age_days <= 30
        stale  — age_days > 30
    """

    fresh: int = 0
    mature: int = 0
    stale: int = 0


class EquipmentExposureRow(BaseModel):
    """Per-equipment rollup of open predictions, sorted by total cost."""

    equipment_id: str
    equipment_label: str
    open_count: int
    total_estimated_repair_cost: float
    total_estimated_downtime_hours: float
    worst_risk_tier: RiskTier


class FailureModeImpactRow(BaseModel):
    """Per-mode rollup, sorted by total exposure."""

    failure_mode: FailureMode
    open_count: int
    total_estimated_repair_cost: float


class TopPredictionRow(BaseModel):
    """Compact prediction row for the top-N exposure list."""

    id: str
    equipment_label: str
    risk_tier: RiskTier
    failure_mode: FailureMode
    source: MaintSource
    estimated_repair_cost: float | None = None
    days_until_due: int | None = None
    age_days: int


class CompletedPredictionRow(BaseModel):
    """Compact row for the recent-completions list (status terminal)."""

    id: str
    equipment_label: str
    failure_mode: FailureMode
    status: MaintStatus  # completed | dismissed
    resolved_at: datetime


class PredictiveMaintenanceInsights(BaseModel):
    """Page-body analytics block."""

    risk_tier_breakdown: RiskTierBreakdown
    status_breakdown: MaintStatusBreakdown
    source_breakdown: MaintSourceBreakdown
    failure_mode_breakdown: FailureModeBreakdown
    aging_breakdown: AgingBreakdown
    top_equipment_exposure: list[EquipmentExposureRow]
    failure_mode_impact: list[FailureModeImpactRow]
    top_by_exposure: list[TopPredictionRow]
    recent_completions: list[CompletedPredictionRow]


# --------------------------------------------------------------------------- #
# Detail                                                                      #
# --------------------------------------------------------------------------- #


class PredictionEvidence(BaseModel):
    """One row of supporting evidence in the detail drawer."""

    label: str
    value: str
    link: str | None = None


class RecentWorkOrder(BaseModel):
    """Trailing work-order summary surfaced on the detail page."""

    wo_number: str
    description: str | None = None
    closed_at: datetime | None = None
    cost: float | None = None


class PredictionHistoryEntry(BaseModel):
    """One row of the per-prediction status-transition log."""

    at: datetime
    status: MaintStatus
    note: str | None = None


class PredictionDetail(BaseModel):
    """Full payload for ``GET /{prediction_id}``."""

    id: str

    equipment_id: str
    equipment_label: str
    equipment_class: str | None = None

    risk_tier: RiskTier
    status: MaintStatus
    source: MaintSource
    failure_mode: FailureMode

    predicted_failure_date: datetime | None = None
    pm_due_date: datetime | None = None
    days_until_due: int | None = None

    estimated_downtime_hours: float | None = None
    estimated_repair_cost: float | None = None

    recommended_action: str
    description: str

    created_at: datetime
    updated_at: datetime
    scheduled_for: datetime | None = None
    age_days: int

    evidence: list[PredictionEvidence] = Field(default_factory=list)
    recent_work_orders: list[RecentWorkOrder] = Field(default_factory=list)
    history: list[PredictionHistoryEntry] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Mutation request bodies                                                     #
# --------------------------------------------------------------------------- #


class AcknowledgeBody(BaseModel):
    note: str | None = None


class ScheduleBody(BaseModel):
    scheduled_for: datetime = Field(
        ...,
        description="ISO-8601 timestamp when the maintenance is planned.",
    )
    note: str | None = None


class CompleteBody(BaseModel):
    completed_at: datetime | None = Field(
        None,
        description=(
            "ISO-8601 timestamp when the work was finished. Defaults to "
            "the server's current UTC time when omitted."
        ),
    )
    note: str | None = None


class DismissBody(BaseModel):
    reason: str | None = Field(
        None,
        description="Free-form reason logged into the history note.",
    )
