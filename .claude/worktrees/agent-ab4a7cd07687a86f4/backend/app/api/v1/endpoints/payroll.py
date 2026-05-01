"""Payroll endpoints — mechanic timecard submission and Vista preh sync."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from agents.mechanic_timecard.agent import parse_timecard, parse_crew_timecards
from app.services.vista_sync import get_payroll_hours, post_payroll_record
from datetime import date

router = APIRouter()


class TimecardRequest(BaseModel):
    employee_id: str
    week_ending: str
    timecard_text: str
    pay_rate: float = 0.0
    auto_post: bool = False


class CrewTimecardRequest(BaseModel):
    timecards: list[TimecardRequest]
    auto_post: bool = False


@router.post("/timecards/parse")
def parse_single_timecard(req: TimecardRequest):
    """
    Parse a mechanic timecard into Vista preh records.
    Handles OT/DT splitting, WO/job mapping, and flags for review.
    If auto_post=true, posts approved records to Vista automatically.
    """
    result = parse_timecard(
        timecard_text=req.timecard_text,
        employee_id=req.employee_id,
        week_ending=req.week_ending,
        pay_rate=req.pay_rate,
    )

    if req.auto_post and not result.get("flags"):
        posted = []
        for rec in result.get("records", []):
            try:
                vista_result = post_payroll_record(
                    employee=rec["employee"],
                    week_ending=rec["week_ending"],
                    job_number=rec["job_number"],
                    phase=rec["phase"],
                    cost_type=rec["cost_type"],
                    hours=rec["hours"],
                    pay_rate=rec.get("pay_rate", req.pay_rate),
                    equipment=rec.get("equipment", ""),
                )
                posted.append(vista_result)
            except Exception as e:
                result.setdefault("post_errors", []).append(str(e))
        result["posted_to_vista"] = posted

    return result


@router.post("/timecards/crew")
def parse_crew_timecards_endpoint(req: CrewTimecardRequest):
    """Parse multiple timecards for a full crew in one call."""
    crew_data = [tc.dict() for tc in req.timecards]
    records = parse_crew_timecards(crew_data)

    if req.auto_post:
        posted = []
        errors = []
        for rec in records:
            if rec.get("needs_review"):
                continue
            try:
                vista_result = post_payroll_record(
                    employee=rec["employee"],
                    week_ending=rec["week_ending"],
                    job_number=rec["job_number"],
                    phase=rec["phase"],
                    cost_type=rec["cost_type"],
                    hours=rec["hours"],
                    pay_rate=rec.get("pay_rate", 0),
                    equipment=rec.get("equipment", ""),
                )
                posted.append(vista_result)
            except Exception as e:
                errors.append({"record": rec, "error": str(e)})
        return {"records": records, "posted_count": len(posted), "errors": errors}

    return {"records": records, "total": len(records)}


@router.get("/timecards")
def get_payroll_records(
    mechanic: Optional[str] = None,
    week_ending: Optional[date] = None,
):
    """Read payroll records from Vista preh."""
    return get_payroll_hours(mechanic=mechanic, week_ending=week_ending)
