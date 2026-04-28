"""Fleet analytics endpoints — P&L, utilization, downtime cost modeling."""
from datetime import date
from fastapi import APIRouter, Query
from agents.fleet_pl.agent import calculate_fleet_pl
from agents.downtime_cost.agent import model_downtime_cost, quick_downtime_cost
from app.services.vista_sync import (
    get_equipment, get_work_orders, get_equipment_utilization,
    get_equipment_downtime,
)

router = APIRouter()


@router.get("/pl")
def fleet_profit_loss(
    start: date = Query(...),
    end: date = Query(...),
):
    """
    Fleet P&L by asset class for a period.
    Revenue vs. cost per unit — shows which equipment makes money.
    """
    utilization = get_equipment_utilization(start, end)
    work_orders = get_work_orders(status="C")  # closed WOs = actual costs
    equipment = get_equipment()
    return calculate_fleet_pl(utilization, work_orders, equipment,
                               str(start), str(end))


@router.get("/utilization")
def fleet_utilization(
    start: date = Query(...),
    end: date = Query(...),
):
    """Billed hours, job count, and revenue per equipment unit from Vista."""
    return get_equipment_utilization(start, end)


@router.get("/downtime-cost")
def downtime_cost_report(
    start: date = Query(...),
    end: date = Query(...),
):
    """
    Dollar impact of equipment downtime.
    Converts downtime hours into Vista job cost terms — not generic estimates.
    """
    downtime = get_equipment_downtime(start, end)
    from app.services.vista_sync import get_job_cost
    jobs = get_job_cost()
    return model_downtime_cost(
        downtime_records=downtime,
        job_cost_data=jobs,
        equipment_rates={},  # TODO: populate from equipment rate table
        period_start=str(start),
        period_end=str(end),
    )


@router.get("/downtime-cost/quick")
def quick_downtime(
    equipment_id: str = Query(...),
    downtime_hours: float = Query(...),
    billing_rate: float = Query(...),
):
    """Fast downtime cost calculation: hours × rate. No AI overhead."""
    cost = quick_downtime_cost(equipment_id, downtime_hours, billing_rate)
    return {"equipment_id": equipment_id, "downtime_hours": downtime_hours,
            "billing_rate": billing_rate, "downtime_cost": cost}
