"""Equipment endpoints — master data, work orders, downtime."""
from datetime import date
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.services.vista_sync import (
    get_equipment, get_work_orders, get_equipment_downtime,
    get_equipment_utilization, create_work_order,
)
from agents.work_order_sync.agent import generate_work_order
from agents.predictive_maintenance.agent import predict_failures, check_pm_overdue
from agents.notifications.agent import build_notification, NotificationEvent

router = APIRouter()


class WorkOrderRequest(BaseModel):
    equipment_id: str
    description: str
    priority: str = "3"
    requested_by: str
    job_number: str = ""


class AlertWorkOrderRequest(BaseModel):
    alert_text: str
    equipment_id: str
    job_number: str = ""
    requested_by: str = "FieldBridge"


@router.get("/")
def list_equipment(equipment_id: Optional[str] = None):
    """List active equipment from Vista emem."""
    return get_equipment(equipment_id)


@router.get("/{equipment_id}/work-orders")
def equipment_work_orders(equipment_id: str, status: Optional[str] = None):
    """Get work orders for a specific equipment unit."""
    return get_work_orders(equipment_id=equipment_id, status=status)


@router.post("/{equipment_id}/work-orders")
def create_equipment_work_order(equipment_id: str, req: WorkOrderRequest):
    """Create a new work order in Vista for this equipment unit."""
    return create_work_order(
        equipment=equipment_id,
        description=req.description,
        priority=req.priority,
        requested_by=req.requested_by,
        job_number=req.job_number,
    )


@router.post("/{equipment_id}/work-orders/from-alert")
def work_order_from_alert(equipment_id: str, req: AlertWorkOrderRequest):
    """
    AI-powered: convert a telematics alert or fault description into a Vista
    work order. Returns the AI-classified WO payload ready for Vista.
    """
    equipment = get_equipment(equipment_id)
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found")

    eq = equipment[0]
    wo_payload = generate_work_order(
        alert_text=req.alert_text,
        equipment_id=equipment_id,
        equipment_desc=eq.get("Description", ""),
        job_number=req.job_number,
        requested_by=req.requested_by,
    )

    # Auto-create in Vista if critical
    if wo_payload.get("priority") == "1":
        result = create_work_order(
            equipment=equipment_id,
            description=wo_payload["description"],
            priority="1",
            requested_by=req.requested_by,
            job_number=req.job_number,
        )
        wo_payload["vista_work_order"] = result

    return wo_payload


@router.get("/downtime/report")
def downtime_report(
    start: date = Query(...),
    end: date = Query(...),
):
    """Equipment downtime report for a date range from Vista work orders."""
    return get_equipment_downtime(start, end)


@router.get("/utilization/report")
def utilization_report(
    start: date = Query(...),
    end: date = Query(...),
):
    """Equipment utilization summary (billed hours + revenue) from Vista."""
    return get_equipment_utilization(start, end)


@router.get("/maintenance/pm-due")
def pm_due():
    """Fast check: equipment with overdue or upcoming PMs from Vista emem."""
    equipment = get_equipment()
    return check_pm_overdue(equipment)


@router.get("/maintenance/predictions")
def maintenance_predictions():
    """
    AI-powered predictive maintenance alerts based on work order history.
    Returns risk-ranked list of equipment likely to fail.
    """
    equipment = get_equipment()
    work_orders = get_work_orders()
    return predict_failures(
        equipment_history=work_orders,
        pm_schedule=equipment,
    )
