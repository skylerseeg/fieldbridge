"""Asset tracking endpoints — rental equipment, small tools, movement replay."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from agents.asset_tracking.agent import (
    analyze_rentals, track_small_tools, log_asset_movement, get_movement_history
)
from app.services.vista_sync import get_job_cost

router = APIRouter()

# In-memory stores — replace with PostgreSQL in production
_rental_records: list[dict] = []
_tool_assignments: list[dict] = []
_movement_log: list[dict] = []


class RentalRecord(BaseModel):
    rental_id: str
    description: str
    vendor: str
    daily_rate: float
    on_rent_since: str
    assigned_job: str = ""
    notes: str = ""


class ToolAssignment(BaseModel):
    tool_id: str
    description: str
    assigned_to: str
    job_number: str
    date_out: str
    expected_return: str = ""
    charge_rate: float = 0.0
    date_in: str = ""


class ToolReturn(BaseModel):
    date_in: str


@router.get("/rental")
def list_rentals():
    """List all active rental assets with cost-to-date from Vista job cost."""
    return _rental_records


@router.post("/rental")
def add_rental(rec: RentalRecord):
    """Add a rental asset to tracking."""
    _rental_records.append(rec.dict())
    return rec


@router.get("/rental/analysis")
def rental_analysis():
    """
    AI-powered rental analysis: idle time, cost recovery, buy/rent/retire decisions.
    Compares rental spend against Vista job cost recovery to find the gap.
    """
    job_cost = get_job_cost()
    return analyze_rentals(_rental_records, job_cost)


@router.get("/tools")
def list_tools(job_number: Optional[str] = None):
    """List small tool assignments, optionally filtered by job."""
    if job_number:
        return [t for t in _tool_assignments if t.get("job_number") == job_number]
    return _tool_assignments


@router.post("/tools")
def assign_tool(assignment: ToolAssignment):
    """Check out a small tool to a job/employee."""
    _tool_assignments.append(assignment.dict())
    return assignment


@router.post("/tools/{tool_id}/return")
def return_tool(tool_id: str, req: ToolReturn):
    """Record tool return."""
    for t in _tool_assignments:
        if t.get("tool_id") == tool_id and not t.get("date_in"):
            t["date_in"] = req.date_in
            return t
    raise HTTPException(status_code=404, detail="Tool assignment not found")


@router.get("/tools/summary")
def tools_summary():
    """Summary of small tool assignments — checked out, overdue, charge by job."""
    return track_small_tools(_tool_assignments)


@router.get("/{equipment_id}/movement")
def asset_movement_replay(equipment_id: str):
    """Get full movement history for an equipment unit — chronological replay."""
    return get_movement_history(equipment_id, _movement_log)
