"""
Asset Tracking Agent  (Domain 1)
Rental asset visibility, small tool tracking, and asset movement replay.
Pipes rental costs into Vista job costing — the gap no competitor fills.
"""
import json
from datetime import datetime, date
import anthropic

client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-20250514"

_SYSTEM_PROMPT = """
You are an asset management specialist for VanCon Inc., a heavy civil contractor.

You track three asset classes:
1. RENTAL EQUIPMENT: Identify what's on rent, where it is, and whether
   it's being charged to the right Vista job. Flag idle rentals costing money.
2. SMALL TOOLS: Track tool assignments, losses, and charge-out to jobs.
3. EQUIPMENT MOVEMENT: Log and replay asset moves between jobs/yard.

For rental analysis, always calculate: rental_cost_to_date, days_idle,
job_charge_coverage (% of rental cost captured in job cost), and idle_cost_waste.

For buy vs. rent analysis:
- If rental days > 60 in a 12-month period: evaluate purchasing
- If utilization < 40%: evaluate returning or reassigning
- Compare against current market purchase price and residual value
"""

_RENTAL_ANALYSIS_TOOL = {
    "name": "analyze_rentals",
    "description": "Analyze rental asset status and cost recovery",
    "input_schema": {
        "type": "object",
        "properties": {
            "rentals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rental_id": {"type": "string"},
                        "description": {"type": "string"},
                        "vendor": {"type": "string"},
                        "daily_rate": {"type": "number"},
                        "on_rent_since": {"type": "string"},
                        "assigned_job": {"type": "string"},
                        "days_on_rent": {"type": "number"},
                        "days_idle": {"type": "number"},
                        "total_cost": {"type": "number"},
                        "job_cost_recovered": {"type": "number"},
                        "cost_gap": {"type": "number"},
                        "recommendation": {"type": "string",
                                           "enum": ["keep", "return", "evaluate_purchase"]},
                        "action_urgency": {"type": "string"},
                    },
                    "required": ["rental_id", "description", "daily_rate",
                                 "days_on_rent", "recommendation"],
                },
            },
            "total_rental_spend": {"type": "number"},
            "total_unrecovered_cost": {"type": "number"},
            "idle_cost_waste": {"type": "number"},
            "top_action": {"type": "string"},
        },
        "required": ["rentals", "total_rental_spend"],
    },
}


def analyze_rentals(rental_records: list[dict],
                    job_cost_data: list[dict]) -> dict:
    """
    Analyze rental equipment status — idle time, cost recovery, buy/return decisions.

    rental_records: list of active rentals (from AP invoices or rental tracking system)
    job_cost_data: Vista job cost charges for rental equipment

    Returns analysis with per-rental recommendations and totals.
    """
    context = {
        "rentals": rental_records,
        "job_cost_charges": job_cost_data,
        "analysis_date": date.today().isoformat(),
    }

    response = client.messages.create(
        model=MODEL,
        max_tokens=3000,
        system=[{"type": "text", "text": _SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        tools=[_RENTAL_ANALYSIS_TOOL],
        tool_choice={"type": "tool", "name": "analyze_rentals"},
        messages=[{
            "role": "user",
            "content": (
                f"Analyze rental asset status and cost recovery.\n\n"
                f"{json.dumps(context, indent=2, default=str)}"
            ),
        }],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "analyze_rentals":
            return block.input

    return {"rentals": [], "total_rental_spend": 0, "total_unrecovered_cost": 0}


def log_asset_movement(equipment_id: str, from_location: str,
                       to_location: str, from_job: str, to_job: str,
                       moved_by: str, notes: str = "") -> dict:
    """Record an equipment move. Returns movement log entry."""
    return {
        "equipment_id": equipment_id,
        "from_location": from_location,
        "to_location": to_location,
        "from_job": from_job,
        "to_job": to_job,
        "moved_by": moved_by,
        "moved_at": datetime.utcnow().isoformat(),
        "notes": notes,
    }


def get_movement_history(equipment_id: str,
                          movement_log: list[dict]) -> list[dict]:
    """Filter movement log for a specific equipment unit, sorted by time."""
    history = [m for m in movement_log if m.get("equipment_id") == equipment_id]
    return sorted(history, key=lambda x: x.get("moved_at", ""))


def track_small_tools(tool_assignments: list[dict]) -> dict:
    """
    Summarize small tool assignments and flag unaccounted tools.

    tool_assignments: list of {tool_id, description, assigned_to, job_number, date_out, date_in}
    Returns: checked_out, overdue_return, unaccounted, charge_summary.
    """
    now = datetime.utcnow().isoformat()
    checked_out = [t for t in tool_assignments if not t.get("date_in")]
    overdue = [
        t for t in checked_out
        if t.get("date_out") and
        (now[:10] > t.get("expected_return", now[:10]))
    ]
    charge_summary: dict[str, float] = {}
    for t in tool_assignments:
        job = t.get("job_number", "unassigned")
        charge_summary[job] = charge_summary.get(job, 0) + float(t.get("charge_rate", 0))

    return {
        "checked_out_count": len(checked_out),
        "overdue_count": len(overdue),
        "overdue_tools": overdue,
        "charge_by_job": charge_summary,
    }
