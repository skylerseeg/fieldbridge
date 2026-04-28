"""Cost-coding module — reads ``mart_hcss_activities``.

Each mart row is one (estimate, activity_code) line item with a cost
breakdown across five buckets: labor, permanent material, construction
material, equipment, subcontract. This module aggregates *by activity
code* across every estimate the code has ever appeared in, surfacing
cost-category mix, usage patterns, and data-hygiene gaps (codes with
zero cost across all estimates).
"""
from app.modules.cost_coding.router import router

__all__ = ["router"]
