"""Safety endpoints — scorecard, incident logging, near-miss tracking."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from agents.safety.agent import log_incident, calculate_safety_scorecard

router = APIRouter()

# In-memory store for demo — replace with PostgreSQL in production
_incident_store: list[dict] = []


class IncidentRequest(BaseModel):
    description: str
    date_of_incident: str
    job_number: str
    employee_id: str
    equipment_id: str = ""
    witness_statements: Optional[list[str]] = None


class ScorecardRequest(BaseModel):
    total_hours_worked: float
    active_jobs: list[str] = []


@router.post("/incidents")
def create_incident(req: IncidentRequest):
    """
    Log a safety incident or near-miss. AI classifies OSHA type, root cause,
    and generates corrective actions. If equipment involved, creates WO recommendation.
    """
    incident = log_incident(
        description=req.description,
        date_of_incident=req.date_of_incident,
        job_number=req.job_number,
        employee_id=req.employee_id,
        equipment_id=req.equipment_id,
        witness_statements=req.witness_statements,
    )
    _incident_store.append(incident)
    return incident


@router.get("/incidents")
def list_incidents(job_number: Optional[str] = None):
    """List all logged safety incidents, optionally filtered by job."""
    if job_number:
        return [i for i in _incident_store if i.get("job_number") == job_number]
    return _incident_store


@router.get("/incidents/{idx}")
def get_incident(idx: int):
    """Get a specific incident by index."""
    if idx < 0 or idx >= len(_incident_store):
        raise HTTPException(status_code=404, detail="Incident not found")
    return _incident_store[idx]


@router.get("/scorecard")
def safety_scorecard(
    total_hours: float = 10000.0,
    active_jobs: str = "",
):
    """
    Calculate safety scorecard — TRIR, DART rate, incident summary.
    Uses logged incidents and provided labor hours from Vista preh.
    """
    jobs = [j.strip() for j in active_jobs.split(",") if j.strip()] if active_jobs else []
    return calculate_safety_scorecard(
        incidents=_incident_store,
        total_hours_worked=total_hours,
        active_jobs=jobs,
    )


@router.delete("/incidents/clear")
def clear_incidents():
    """Clear incident store (dev/testing only)."""
    _incident_store.clear()
    return {"cleared": True}
