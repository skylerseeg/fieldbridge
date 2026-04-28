"""Fleet P&L module — per-truck revenue, invoicing, utilization, and
rental-in costs rolled up from ``mart_equipment_utilization`` and
``mart_equipment_rentals``.
"""
from app.modules.fleet_pnl.router import router

__all__ = ["router"]
