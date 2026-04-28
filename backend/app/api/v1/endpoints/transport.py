"""Transport logistics endpoints — lowboy scheduling and equipment moves."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from agents.transport_logistics.agent import (
    schedule_equipment_moves, check_permit_required,
)
from agents.asset_tracking.agent import log_asset_movement

router = APIRouter()

# In-memory movement log — replace with PostgreSQL in production
_movement_log: list[dict] = []


class MoveRequest(BaseModel):
    equipment_id: str
    equipment_desc: str = ""
    equipment_weight_lbs: float = 0
    from_location: str
    to_location: str
    needed_by: str
    job_number: str = ""


class ScheduleRequest(BaseModel):
    move_requests: list[MoveRequest]
    available_lowboys: list[dict] = []
    available_drivers: list[dict] = []


class LogMoveRequest(BaseModel):
    equipment_id: str
    from_location: str
    to_location: str
    from_job: str
    to_job: str
    moved_by: str
    notes: str = ""


@router.post("/schedule")
def schedule_moves(req: ScheduleRequest):
    """
    AI-optimized lowboy scheduling. Matches equipment to available transport,
    flags permit requirements, and detects conflicts.
    """
    move_requests = [m.dict() for m in req.move_requests]
    return schedule_equipment_moves(
        move_requests=move_requests,
        available_lowboys=req.available_lowboys,
        available_drivers=req.available_drivers,
    )


@router.get("/permit-check")
def permit_check(
    weight_lbs: float,
    route_type: str = "state",
):
    """Quick permit requirement check based on equipment weight."""
    return check_permit_required(weight_lbs, route_type)


@router.post("/moves")
def log_move(req: LogMoveRequest):
    """Record an equipment move for movement history and replay."""
    entry = log_asset_movement(
        equipment_id=req.equipment_id,
        from_location=req.from_location,
        to_location=req.to_location,
        from_job=req.from_job,
        to_job=req.to_job,
        moved_by=req.moved_by,
        notes=req.notes,
    )
    _movement_log.append(entry)
    return entry


@router.get("/moves")
def list_moves(equipment_id: Optional[str] = None):
    """List movement log, optionally filtered by equipment."""
    if equipment_id:
        return [m for m in _movement_log if m.get("equipment_id") == equipment_id]
    return _movement_log
