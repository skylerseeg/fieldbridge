"""Jobs module — reads mart_job_wip, mart_job_schedule, and
mart_estimate_variance (Vista jcjm shape).
"""
from app.modules.jobs.router import router

__all__ = ["router"]
