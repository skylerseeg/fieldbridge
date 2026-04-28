# sys.path bootstrap. The v1 endpoints import `from agents.*` (sibling
# directory at fieldbridge/agents/) and app/models/__init__.py optionally
# imports `from fieldbridge.saas.*` (one level up from that). Add both to
# sys.path so `uvicorn app.main:app` works whether launched from
# fieldbridge/backend/ (the documented cwd) or anywhere else. Tests get
# the same treatment via tests/conftest.py.
import sys
from pathlib import Path

_FIELDBRIDGE_DIR = Path(__file__).resolve().parents[2]   # .../fieldbridge/
_REPO_ROOT = _FIELDBRIDGE_DIR.parent                     # .../fieldbridge_repo/
for _p in (str(_FIELDBRIDGE_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1 import router as api_v1_router
from app.modules.activity_feed import router as activity_feed_module_router
from app.modules.bids import router as bids_module_router
from app.modules.cost_coding import router as cost_coding_module_router
from app.modules.equipment import router as equipment_module_router
from app.modules.executive_dashboard import (
    router as executive_dashboard_module_router,
)
from app.modules.fleet_pnl import router as fleet_pnl_module_router
from app.modules.jobs import router as jobs_module_router
from app.modules.predictive_maintenance import (
    router as predictive_maintenance_module_router,
)
from app.modules.productivity import router as productivity_module_router
from app.modules.proposals import router as proposals_module_router
from app.modules.timecards import router as timecards_module_router
from app.modules.vendors import router as vendors_module_router
from app.modules.work_orders import router as work_orders_module_router

app = FastAPI(
    title="FieldBridge API — VANCON Technologies",
    version="0.3.0",
    description=(
        "Vista ERP + Field Operations Bridge for VanCon Inc. "
        "Equipment, job cost, payroll, fleet analytics, safety, and AI agents."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router, prefix=settings.api_v1_prefix)

# Module routers (mart-backed, non-versioned surface).
# Mounted at /api/<module_name> per the module-build contract.
app.include_router(
    equipment_module_router, prefix="/api/equipment", tags=["Equipment (Marts)"],
)
app.include_router(
    work_orders_module_router,
    prefix="/api/work-orders",
    tags=["Work Orders (Marts)"],
)
app.include_router(
    timecards_module_router,
    prefix="/api/timecards",
    tags=["Timecards (Marts)"],
)
app.include_router(
    jobs_module_router,
    prefix="/api/jobs",
    tags=["Jobs (Marts)"],
)
app.include_router(
    productivity_module_router,
    prefix="/api/productivity",
    tags=["Productivity (Marts)"],
)
app.include_router(
    fleet_pnl_module_router,
    prefix="/api/fleet-pnl",
    tags=["Fleet P&L (Marts)"],
)
app.include_router(
    vendors_module_router,
    prefix="/api/vendors",
    tags=["Vendors (Marts)"],
)
app.include_router(
    cost_coding_module_router,
    prefix="/api/cost-coding",
    tags=["Cost Coding (Marts)"],
)
app.include_router(
    bids_module_router,
    prefix="/api/bids",
    tags=["Bids (Marts)"],
)
app.include_router(
    proposals_module_router,
    prefix="/api/proposals",
    tags=["Proposals (Marts)"],
)
app.include_router(
    executive_dashboard_module_router,
    prefix="/api/executive-dashboard",
    tags=["Executive Dashboard (Marts)"],
)
app.include_router(
    activity_feed_module_router,
    prefix="/api/activity-feed",
    tags=["Activity Feed (Events)"],
)
app.include_router(
    predictive_maintenance_module_router,
    prefix="/api/predictive-maintenance",
    tags=["Predictive Maintenance (Marts)"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.environment, "version": "0.2.0"}
