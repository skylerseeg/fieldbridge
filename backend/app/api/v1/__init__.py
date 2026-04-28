from fastapi import APIRouter
from app.api.v1.endpoints import (
    vendors, equipment, bids, projects, media,
    fleet, safety, dashboard, transport, assets,
    payroll, job_cost, notifications,
    auth, onboarding, admin, sales,
)

router = APIRouter()

# ── Auth & Onboarding (public + tenant-scoped) ────────────────────────────────
router.include_router(auth.router,          prefix="/auth",          tags=["Auth"])
router.include_router(onboarding.router,    prefix="/onboarding",    tags=["Onboarding"])
router.include_router(admin.router,         prefix="/admin",         tags=["Admin"])

# ── Existing ──────────────────────────────────────────────────────────────────
router.include_router(vendors.router,       prefix="/vendors",       tags=["Vendors"])
router.include_router(equipment.router,     prefix="/equipment",     tags=["Equipment"])
router.include_router(bids.router,          prefix="/bids",          tags=["Bids"])
router.include_router(projects.router,      prefix="/projects",      tags=["Projects"])
router.include_router(media.router,         prefix="/media",         tags=["Media"])

# ── Phase 1 — Vista Pipe ──────────────────────────────────────────────────────
router.include_router(job_cost.router,      prefix="/job-cost",      tags=["Job Cost"])
router.include_router(payroll.router,       prefix="/payroll",       tags=["Payroll"])

# ── Phase 2 — Dollars ─────────────────────────────────────────────────────────
router.include_router(fleet.router,         prefix="/fleet",         tags=["Fleet"])

# ── Phase 3 — Intelligence ────────────────────────────────────────────────────
router.include_router(dashboard.router,     prefix="/dashboard",     tags=["Dashboard"])

# ── Domain Features ───────────────────────────────────────────────────────────
router.include_router(safety.router,        prefix="/safety",        tags=["Safety"])
router.include_router(transport.router,     prefix="/transport",     tags=["Transport"])
router.include_router(assets.router,        prefix="/assets",        tags=["Assets"])
router.include_router(notifications.router, prefix="/notifications",  tags=["Notifications"])

# ── VANCON Sales Intelligence (admin-only) ────────────────────────────────────
router.include_router(sales.router,         prefix="/sales",          tags=["Sales Intelligence"])
