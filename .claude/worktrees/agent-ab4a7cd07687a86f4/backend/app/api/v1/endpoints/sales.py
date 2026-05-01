"""
VANCON Technologies — FieldBridge SaaS Sales Pipeline API
Prospect intelligence: scrape, enrich, score, export.

FIELDBRIDGE_ADMIN only — these endpoints are internal to VANCON.
"""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_role
from app.core.database import get_db
from app.models.user import User, UserRole

log = logging.getLogger("fieldbridge.sales")

router = APIRouter()

# ── Lazy imports so the API starts even without scraper deps installed ────────

def _get_prospect_model():
    from fieldbridge.saas.prospect_intelligence.models import Prospect, ProspectContact, ProspectStatus
    return Prospect, ProspectContact, ProspectStatus


def _get_scraper():
    from fieldbridge.saas.prospect_intelligence.scraper import scrape_company
    return scrape_company


def _get_apollo():
    from fieldbridge.saas.prospect_intelligence.apollo_client import enrich_prospect
    return enrich_prospect


def _get_export():
    from fieldbridge.saas.prospect_intelligence.export import export_bucks_list
    return export_bucks_list


def _get_seed():
    from fieldbridge.saas.prospect_intelligence.seed import get_seed_prospects
    return get_seed_prospects


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ProspectCreate(BaseModel):
    company_name: str
    website: str = ""
    state: str = ""
    city: str = ""
    notes: str = ""


class ProspectPatch(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    priority_tier: Optional[str] = None
    assigned_to: Optional[str] = None
    next_follow_up: Optional[datetime] = None


class ScrapeRequest(BaseModel):
    prospect_id: Optional[str] = None
    company_name: Optional[str] = None
    website: Optional[str] = None


class EnrichRequest(BaseModel):
    prospect_id: str


# ── Helper ────────────────────────────────────────────────────────────────────

async def _get_prospect_or_404(prospect_id: str, db: AsyncSession):
    Prospect, _, _ = _get_prospect_model()
    result = await db.execute(select(Prospect).where(Prospect.id == prospect_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Prospect not found")
    return p


def _prospect_to_dict(p) -> dict:
    """Serialize a Prospect ORM object to dict for API response."""
    return {
        "id": p.id,
        "company_name": p.company_name,
        "website": p.website,
        "state": p.state,
        "city": p.city,
        "fit_score": p.fit_score,
        "priority_tier": p.priority_tier.value if p.priority_tier else None,
        "status": p.status.value if p.status else None,
        "uses_vista": p.uses_vista,
        "vista_confirmed": getattr(p, "vista_confirmed", False),
        "technology_mentions": p.technology_mentions,
        "about_summary": p.about_summary,
        "pain_point_signals": p.pain_point_signals,
        "projects_mentioned": p.projects_mentioned,
        "outreach_angle": getattr(p, "outreach_angle", ""),
        "estimated_fleet_size": getattr(p, "estimated_fleet_size", ""),
        "estimated_arr": p.estimated_arr,
        "assigned_to": p.assigned_to,
        "notes": p.notes,
        "scraped_at": p.scraped_at.isoformat() if p.scraped_at else None,
        "contacts": [_contact_to_dict(c) for c in (p.contacts or [])],
    }


def _contact_to_dict(c) -> dict:
    return {
        "id": c.id,
        "full_name": c.full_name,
        "title": c.title,
        "role_category": c.role_category.value if c.role_category else None,
        "email": c.email,
        "phone": c.phone,
        "linkedin_url": c.linkedin_url,
        "is_decision_maker": c.is_decision_maker,
        "is_primary_contact": c.is_primary_contact,
        "email_confidence": c.email_confidence,
        "apollo_person_id": c.apollo_person_id,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/prospects")
async def list_prospects(
    state: Optional[str] = None,
    min_score: int = Query(0, ge=0, le=100),
    status: Optional[str] = None,
    tier: Optional[str] = None,
    vista_only: bool = False,
    limit: int = Query(100, le=500),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FIELDBRIDGE_ADMIN)),
):
    """List prospects with optional filters. Sorted by fit_score desc."""
    Prospect, _, ProspectStatus = _get_prospect_model()
    from fieldbridge.saas.prospect_intelligence.models import ProspectTier

    q = select(Prospect).where(Prospect.fit_score >= min_score)

    if state:
        q = q.where(Prospect.state == state.upper())
    if status:
        try:
            q = q.where(Prospect.status == ProspectStatus(status))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    if tier:
        try:
            q = q.where(Prospect.priority_tier == ProspectTier(tier))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid tier: {tier}")
    if vista_only:
        q = q.where(Prospect.uses_vista == True)  # noqa: E712

    q = q.order_by(Prospect.fit_score.desc()).offset(offset).limit(limit)
    result = await db.execute(q)
    prospects = result.scalars().all()

    return {
        "count": len(prospects),
        "prospects": [_prospect_to_dict(p) for p in prospects],
    }


@router.post("/prospects", status_code=201)
async def create_prospect(
    body: ProspectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FIELDBRIDGE_ADMIN)),
):
    """Manually add a single prospect."""
    Prospect, _, _ = _get_prospect_model()
    p = Prospect(
        company_name=body.company_name,
        website=body.website,
        state=body.state.upper() if body.state else "",
        city=body.city,
        notes=body.notes,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return _prospect_to_dict(p)


@router.get("/prospects/{prospect_id}")
async def get_prospect(
    prospect_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FIELDBRIDGE_ADMIN)),
):
    p = await _get_prospect_or_404(prospect_id, db)
    return _prospect_to_dict(p)


@router.patch("/prospects/{prospect_id}")
async def patch_prospect(
    prospect_id: str,
    body: ProspectPatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FIELDBRIDGE_ADMIN)),
):
    """Update pipeline status, notes, tier, follow-up date."""
    p = await _get_prospect_or_404(prospect_id, db)
    if body.status is not None:
        from fieldbridge.saas.prospect_intelligence.models import ProspectStatus
        try:
            p.status = ProspectStatus(body.status)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {body.status}")
    if body.notes is not None:
        p.notes = body.notes
    if body.priority_tier is not None:
        from fieldbridge.saas.prospect_intelligence.models import ProspectTier
        try:
            p.priority_tier = ProspectTier(body.priority_tier)
        except ValueError:
            raise HTTPException(400, f"Invalid tier: {body.priority_tier}")
    if body.assigned_to is not None:
        p.assigned_to = body.assigned_to
    if body.next_follow_up is not None:
        p.next_follow_up = body.next_follow_up
    p.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(p)
    return _prospect_to_dict(p)


@router.delete("/prospects/{prospect_id}", status_code=204)
async def delete_prospect(
    prospect_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FIELDBRIDGE_ADMIN)),
):
    p = await _get_prospect_or_404(prospect_id, db)
    await db.delete(p)
    await db.commit()


# ── Scraping ──────────────────────────────────────────────────────────────────

@router.post("/prospects/{prospect_id}/scrape")
async def scrape_prospect(
    prospect_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FIELDBRIDGE_ADMIN)),
):
    """Trigger website scrape + Claude analysis for a prospect."""
    p = await _get_prospect_or_404(prospect_id, db)
    if not p.website:
        raise HTTPException(400, "Prospect has no website set")

    background_tasks.add_task(_run_scrape, prospect_id, p.website, p.company_name)
    return {"message": f"Scrape queued for {p.company_name}", "prospect_id": prospect_id}


async def _run_scrape(prospect_id: str, website: str, company_name: str):
    """Background task: scrape + store results."""
    from app.core.database import AsyncSessionLocal
    scrape_company = _get_scraper()
    Prospect, _, ProspectStatus = _get_prospect_model()
    from fieldbridge.saas.prospect_intelligence.models import ProspectTier

    intel = scrape_company(website, company_name)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Prospect).where(Prospect.id == prospect_id))
        p = result.scalar_one_or_none()
        if not p:
            return

        p.fit_score = intel.get("fit_score", 0)
        p.uses_vista = intel.get("vista_confirmed", False)
        p.about_summary = intel.get("company_description", "")[:500]
        p.technology_mentions = json.dumps(intel.get("technology_mentions", []))
        p.pain_point_signals = json.dumps(intel.get("pain_point_signals", []))
        p.projects_mentioned = json.dumps(intel.get("notable_projects", []))
        p.scraped_at = datetime.now(timezone.utc)

        # Store outreach angle in notes if not already set
        angle = intel.get("outreach_angle", "")
        if angle and not p.notes:
            p.notes = f"[AI Outreach Angle] {angle}"

        # Work type flags
        work_types = intel.get("work_types", [])
        p.does_earthwork = "earthwork" in work_types
        p.does_utilities = "utilities" in work_types
        p.does_paving = "paving" in work_types
        p.does_bridges = "bridges" in work_types
        p.does_wastewater = "wastewater" in work_types
        p.does_water = "water" in work_types
        p.does_site_development = "site_development" in work_types

        # Auto-assign tier
        score = p.fit_score
        if score >= 75:
            p.priority_tier = ProspectTier.TIER_1
        elif score >= 50:
            p.priority_tier = ProspectTier.TIER_2
        else:
            p.priority_tier = ProspectTier.TIER_3

        if intel.get("disqualified"):
            p.status = ProspectStatus.NOT_QUALIFIED
        elif p.status == ProspectStatus.IDENTIFIED:
            p.status = ProspectStatus.RESEARCHED

        await db.commit()
        log.info(f"Scrape complete: {company_name} score={score}")


@router.post("/prospects/scrape-batch")
async def scrape_batch(
    background_tasks: BackgroundTasks,
    min_score_filter: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FIELDBRIDGE_ADMIN)),
):
    """Queue scraping for all unscraped prospects."""
    Prospect, _, ProspectStatus = _get_prospect_model()
    q = select(Prospect).where(
        Prospect.scraped_at == None,  # noqa: E711
        Prospect.website != "",
        Prospect.status != ProspectStatus.NOT_QUALIFIED,
    ).limit(50)
    result = await db.execute(q)
    prospects = result.scalars().all()

    for p in prospects:
        background_tasks.add_task(_run_scrape, p.id, p.website, p.company_name)

    return {"message": f"Queued {len(prospects)} scrapes"}


# ── Apollo Enrichment ─────────────────────────────────────────────────────────

@router.post("/prospects/{prospect_id}/enrich")
async def enrich_prospect_contacts(
    prospect_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FIELDBRIDGE_ADMIN)),
):
    """Find decision-maker contacts via Apollo.io for a prospect."""
    p = await _get_prospect_or_404(prospect_id, db)
    background_tasks.add_task(
        _run_enrich, prospect_id, p.company_name, p.website, p.apollo_org_id
    )
    return {"message": f"Apollo enrichment queued for {p.company_name}"}


async def _run_enrich(
    prospect_id: str, company_name: str, website: str, existing_org_id: str
):
    from app.core.database import AsyncSessionLocal
    enrich = _get_apollo()
    Prospect, ProspectContact, ProspectStatus = _get_prospect_model()
    from fieldbridge.saas.prospect_intelligence.models import ContactRole

    result_data = enrich(
        company_name=company_name,
        website=website,
        existing_apollo_org_id=existing_org_id,
    )

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Prospect).where(Prospect.id == prospect_id))
        p = res.scalar_one_or_none()
        if not p:
            return

        if result_data.get("apollo_org_id"):
            p.apollo_org_id = result_data["apollo_org_id"]

        # Delete old Apollo contacts before re-inserting
        existing = await db.execute(
            select(ProspectContact).where(
                ProspectContact.prospect_id == prospect_id,
                ProspectContact.source == "apollo",
            )
        )
        for old_c in existing.scalars().all():
            await db.delete(old_c)

        for c_data in result_data.get("contacts", []):
            try:
                role = ContactRole(c_data.get("role_category", "Other"))
            except ValueError:
                role = ContactRole.OTHER

            contact = ProspectContact(
                prospect_id=prospect_id,
                full_name=c_data.get("full_name", ""),
                title=c_data.get("title", ""),
                role_category=role,
                email=c_data.get("email", ""),
                phone=c_data.get("phone", ""),
                linkedin_url=c_data.get("linkedin_url", ""),
                apollo_person_id=c_data.get("apollo_person_id", ""),
                email_confidence=c_data.get("email_confidence", 0),
                is_decision_maker=c_data.get("is_decision_maker", False),
                is_primary_contact=c_data.get("is_primary_contact", False),
                source="apollo",
                enriched_at=datetime.now(timezone.utc),
            )
            db.add(contact)

        if p.status == ProspectStatus.RESEARCHED:
            p.status = ProspectStatus.ENRICHED

        await db.commit()
        log.info(
            f"Enrichment complete: {company_name} — "
            f"{result_data.get('contacts_found', 0)} contacts"
        )


@router.post("/prospects/enrich-batch")
async def enrich_batch(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FIELDBRIDGE_ADMIN)),
):
    """Queue Apollo enrichment for all scraped but not-yet-enriched prospects."""
    Prospect, ProspectContact, ProspectStatus = _get_prospect_model()

    # Prospects in RESEARCHED status with no contacts yet
    q = select(Prospect).where(Prospect.status == ProspectStatus.RESEARCHED).limit(30)
    result = await db.execute(q)
    prospects = result.scalars().all()

    for p in prospects:
        background_tasks.add_task(
            _run_enrich, p.id, p.company_name, p.website, p.apollo_org_id
        )

    return {"message": f"Queued {len(prospects)} Apollo enrichments"}


# ── Seed / Import ─────────────────────────────────────────────────────────────

@router.post("/prospects/seed", status_code=201)
async def seed_prospects(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FIELDBRIDGE_ADMIN)),
):
    """
    Load the 120-prospect seed list into the database.
    Skips companies already present (by company_name).
    """
    Prospect, _, _ = _get_prospect_model()
    get_seed = _get_seed()
    seed_list = get_seed()

    existing_result = await db.execute(select(Prospect.company_name))
    existing_names = {row[0].lower() for row in existing_result.all()}

    added = 0
    skipped = 0
    for item in seed_list:
        if item["company_name"].lower() in existing_names:
            skipped += 1
            continue
        p = Prospect(
            company_name=item["company_name"],
            website=item.get("website", ""),
            state=item.get("state", "").upper(),
            city=item.get("city", ""),
            notes=item.get("notes", ""),
        )
        db.add(p)
        added += 1

    await db.commit()
    return {
        "message": f"Seeded {added} new prospects ({skipped} already existed)",
        "added": added,
        "skipped": skipped,
    }


# ── Export ────────────────────────────────────────────────────────────────────

@router.get("/prospects/export/xlsx")
async def export_xlsx(
    min_score: int = Query(0, ge=0, le=100),
    state: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FIELDBRIDGE_ADMIN)),
):
    """
    Download Buck's outreach list as a formatted Excel workbook.
    Includes hot leads sheet, all prospects, contacts, and pipeline stats.
    """
    Prospect, _, _ = _get_prospect_model()
    export_bucks_list = _get_export()

    q = select(Prospect).where(Prospect.fit_score >= min_score)
    if state:
        q = q.where(Prospect.state == state.upper())
    q = q.order_by(Prospect.fit_score.desc())
    result = await db.execute(q)
    prospects = result.scalars().all()

    data = []
    for p in prospects:
        d = _prospect_to_dict(p)
        # Add estimated_fleet_size if available
        d["estimated_fleet_size"] = getattr(p, "estimated_fleet_size", "")
        d["vista_confirmed"] = getattr(p, "vista_confirmed", p.uses_vista)
        d["outreach_angle"] = p.notes.replace("[AI Outreach Angle] ", "") if p.notes.startswith("[AI Outreach Angle]") else ""
        data.append(d)

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        path = tmp.name

    export_bucks_list(data, output_path=path)

    filename = f"vancon_prospects_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return FileResponse(
        path=path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
        background=BackgroundTasks(),
    )


# ── Dashboard stats ───────────────────────────────────────────────────────────

@router.get("/prospects/stats/summary")
async def prospect_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FIELDBRIDGE_ADMIN)),
):
    """High-level pipeline stats for the VANCON sales dashboard."""
    Prospect, ProspectContact, ProspectStatus = _get_prospect_model()

    total = await db.scalar(select(func.count(Prospect.id)))
    hot = await db.scalar(select(func.count(Prospect.id)).where(Prospect.fit_score >= 70))
    vista_confirmed = await db.scalar(
        select(func.count(Prospect.id)).where(Prospect.uses_vista == True)  # noqa: E712
    )
    enriched = await db.scalar(
        select(func.count(Prospect.id)).where(Prospect.status.in_([
            ProspectStatus.ENRICHED, ProspectStatus.OUTREACH_READY,
            ProspectStatus.CONTACTED, ProspectStatus.DEMO_SCHEDULED,
        ]))
    )
    total_contacts = await db.scalar(select(func.count(ProspectContact.id)))
    avg_score = await db.scalar(select(func.avg(Prospect.fit_score)))

    return {
        "total_prospects": total,
        "hot_leads": hot,
        "vista_confirmed": vista_confirmed,
        "enriched_with_contacts": enriched,
        "total_contacts": total_contacts,
        "avg_fit_score": round(float(avg_score or 0), 1),
        "pipeline_arr_estimate": hot * 60_000,  # conservative: hot leads at T2 rate
    }
