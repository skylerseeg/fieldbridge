"""
Transport Logistics Agent  (Domain 5)
Lowboy scheduling, equipment move coordination, and permit management.
Completely manual at most heavy civil firms — FieldBridge owns this gap.
"""
import json
from datetime import datetime, date
import anthropic

client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-20250514"

_SYSTEM_PROMPT = """
You are a heavy haul logistics coordinator for VanCon Inc., a heavy civil contractor.

You coordinate:
1. LOWBOY SCHEDULING: Match equipment needing transport with available lowboy/float
   and drivers. Optimize routes to minimize dead-head miles and permit costs.
2. OVERSIZE PERMITS: Flag moves requiring oversize/overweight permits, estimate
   permit lead times (state routes: 1-3 days, interstate: 3-10 days).
3. MOVE SEQUENCING: Sequence equipment moves to serve job needs — equipment
   must arrive before the crew needs it, not after.
4. CONFLICT DETECTION: Identify schedule conflicts where the same lowboy
   is booked for multiple simultaneous moves.

Key rules for heavy civil equipment moves:
- Excavators >90,000 lbs: require permit, pilot car may be required
- Dozers (D8+): typically over 80,000 lbs — permit required
- Standard floats: max 48,000 lbs net load
- Lowboy travel times: average 45 mph loaded, 55 mph empty
- Add 1 hour for load/unload each way
- Night moves preferred for urban routes
"""

_SCHEDULE_TOOL = {
    "name": "schedule_moves",
    "description": "Generate an optimized equipment transport schedule",
    "input_schema": {
        "type": "object",
        "properties": {
            "moves": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "move_id": {"type": "string"},
                        "equipment_id": {"type": "string"},
                        "equipment_desc": {"type": "string"},
                        "equipment_weight_lbs": {"type": "number"},
                        "from_location": {"type": "string"},
                        "to_location": {"type": "string"},
                        "needed_by": {"type": "string", "description": "datetime"},
                        "assigned_lowboy": {"type": "string"},
                        "assigned_driver": {"type": "string"},
                        "scheduled_departure": {"type": "string"},
                        "estimated_arrival": {"type": "string"},
                        "permit_required": {"type": "boolean"},
                        "permit_lead_days": {"type": "integer"},
                        "notes": {"type": "string"},
                    },
                    "required": ["move_id", "equipment_id", "from_location",
                                 "to_location", "needed_by"],
                },
            },
            "conflicts": {
                "type": "array",
                "items": {"type": "object",
                          "properties": {"description": {"type": "string"},
                                         "affected_moves": {"type": "array",
                                                            "items": {"type": "string"}}},
                          "required": ["description"]},
            },
            "permit_alerts": {"type": "array", "items": {"type": "string"}},
            "optimization_notes": {"type": "string"},
        },
        "required": ["moves"],
    },
}


def schedule_equipment_moves(move_requests: list[dict],
                              available_lowboys: list[dict],
                              available_drivers: list[dict]) -> dict:
    """
    Generate an optimized lowboy transport schedule.

    move_requests: list of {equipment_id, equipment_desc, weight_lbs,
                            from_location, to_location, needed_by, job_number}
    available_lowboys: list of {lowboy_id, description, max_load_lbs, location}
    available_drivers: list of {driver_id, name, license_class, available_from}

    Returns optimized schedule with conflict flags and permit alerts.
    """
    context = {
        "move_requests": move_requests,
        "available_lowboys": available_lowboys,
        "available_drivers": available_drivers,
        "current_datetime": datetime.utcnow().isoformat(),
    }

    response = client.messages.create(
        model=MODEL,
        max_tokens=3000,
        system=[{"type": "text", "text": _SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        tools=[_SCHEDULE_TOOL],
        tool_choice={"type": "tool", "name": "schedule_moves"},
        messages=[{
            "role": "user",
            "content": (
                f"Schedule these equipment moves.\n\n"
                f"{json.dumps(context, indent=2, default=str)}"
            ),
        }],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "schedule_moves":
            return block.input

    return {"moves": move_requests, "conflicts": [], "permit_alerts": []}


def check_permit_required(equipment_weight_lbs: float,
                           route_type: str = "state") -> dict:
    """Quick check: does this move require a permit? No AI needed."""
    needs_permit = equipment_weight_lbs > 48000
    if needs_permit:
        lead_days = 3 if route_type == "state" else 7
    else:
        lead_days = 0
    return {
        "permit_required": needs_permit,
        "estimated_lead_days": lead_days,
        "pilot_car_required": equipment_weight_lbs > 100000,
    }
