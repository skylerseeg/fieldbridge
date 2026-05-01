"""predictive_maintenance writers — populate ``mart_predictive_maintenance``.

Two passes (see [docs/ARCHITECTURE.md] Phase 3):

  * ``pm_overdue``        — deterministic, runs daily.
  * ``failure_predict``   — Claude agent, runs weekly.

Read side lives in :mod:`app.modules.predictive_maintenance` and queries
the same marts.
"""
from app.services.predictive_maintenance.failure_predict import (
    FailurePredictResult,
    write_failure_predictions,
)
from app.services.predictive_maintenance.pm_overdue import (
    PmOverdueResult,
    write_pm_overdue,
)

__all__ = [
    "FailurePredictResult",
    "PmOverdueResult",
    "write_failure_predictions",
    "write_pm_overdue",
]
