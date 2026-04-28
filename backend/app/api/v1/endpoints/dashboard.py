"""Dashboard endpoints — executive summary and AI recommendations."""
from datetime import date, timedelta
from fastapi import APIRouter, Query
from agents.executive_dashboard.agent import generate_dashboard
from agents.ai_recommendations.agent import generate_recommendations
from app.services.vista_sync import (
    get_equipment, get_work_orders, get_job_cost,
    get_equipment_utilization, get_equipment_downtime,
)
from agents.predictive_maintenance.agent import check_pm_overdue

router = APIRouter()


@router.get("/executive")
def executive_dashboard(period_label: str = Query(default="This Week")):
    """
    One-page executive dashboard pulling from Vista financials + field ops.
    Red/yellow/green status per section. Built on the Vista pipe.
    """
    today = date.today()
    week_start = today - timedelta(days=7)

    # Aggregate data from Vista
    jobs = get_job_cost()
    equipment = get_equipment()
    work_orders = get_work_orders(status="O")  # open WOs
    utilization = get_equipment_utilization(week_start, today)
    downtime = get_equipment_downtime(week_start, today)
    pm_due = check_pm_overdue(equipment)

    # Build section payloads
    financial_data = {
        "active_jobs": len({j["Job"] for j in jobs if j.get("Job")}),
        "jobs_detail": jobs[:10],
    }
    fleet_data = {
        "active_equipment": len(equipment),
        "open_work_orders": len(work_orders),
        "utilization_summary": utilization[:10],
        "downtime_events": len(downtime),
        "pm_overdue_count": len([p for p in pm_due if p["status"] == "OVERDUE"]),
    }
    safety_data = {"open_safety_items": 0}  # populated from safety service in production
    operations_data = {
        "open_work_orders": work_orders[:5],
        "pm_due_soon": [p for p in pm_due if p["status"] == "DUE_SOON"][:5],
    }

    return generate_dashboard(
        financial_data=financial_data,
        fleet_data=fleet_data,
        safety_data=safety_data,
        operations_data=operations_data,
        period_label=period_label,
    )


@router.get("/recommendations")
def ai_recommendations():
    """
    Proactive AI recommendations from Vista data — prioritized P1/P2/P3.
    Every recommendation cites specific data, dollar impact, action, and owner.
    """
    today = date.today()
    week_start = today - timedelta(days=7)

    equipment = get_equipment()
    pm_overdue = check_pm_overdue(equipment)
    open_wos = get_work_orders(status="O")
    jobs = get_job_cost()
    downtime = get_equipment_downtime(week_start, today)

    snapshot = {
        "open_work_orders": open_wos[:20],
        "pm_overdue": pm_overdue,
        "downtime_summary": {
            "event_count": len(downtime),
            "events": downtime[:10],
        },
        "job_cost_variances": [
            j for j in jobs
            if j.get("PhaseActual") and j.get("PhaseEst") and
            float(j.get("PhaseActual", 0)) > float(j.get("PhaseEst", 1)) * 1.1
        ][:10],
    }

    return generate_recommendations(snapshot)
