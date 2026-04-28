"""Vendors module — reads ``mart_vendors`` (firm/contact directory).

Surfaces firm-type mix, contact-data completeness, and CSI-code
coverage across ``apvend``-equivalent rows.
"""
from app.modules.vendors.router import router

__all__ = ["router"]
