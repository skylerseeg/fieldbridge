"""predictive_maintenance module — equipment failure predictions + PM queue.

Mounted at ``/api/predictive-maintenance`` (no /api/v1/ prefix), to match
the Phase-5 mart-backed module convention.
"""
from app.modules.predictive_maintenance.router import router

__all__ = ["router"]
