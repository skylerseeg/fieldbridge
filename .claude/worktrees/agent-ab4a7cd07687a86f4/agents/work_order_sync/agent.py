"""
Work Order Sync Agent  (Phase 1 — Vista Pipe)
Converts equipment telematics alerts and foreman fault reports into
Vista emwo work orders via the REST API. Closes the loop between field
and shop without manual data entry.
"""
import json
import anthropic

client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-20250514"

_SYSTEM_PROMPT = """
You are a heavy equipment maintenance coordinator for VanCon Inc.

Given an equipment fault alert or foreman report, produce a Vista work order:
- Description: clear, actionable, ≤60 chars (Vista field limit)
- Priority: 1=Critical (equipment down), 2=High (degraded operation), 3=Normal (PM/minor)
- Suggested mechanic assignment based on equipment type and specialty
- Safety flag: true if operating the equipment in current state is unsafe

Equipment type → mechanic specialty guide:
- Excavators, dozers, scrapers → Heavy Iron
- Haul trucks, water trucks → Trucks
- Compactors, pavers → Paving
- Pumps, generators → Power Equipment
- Any hydraulic leak → Critical, assign Heavy Iron

Keep descriptions factual. Do not include fault codes verbatim — translate to plain language.
"""

_WO_TOOL = {
    "name": "create_work_order",
    "description": "Generate a Vista work order from an equipment alert",
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {"type": "string", "maxLength": 60},
            "priority": {"type": "string", "enum": ["1", "2", "3"]},
            "mechanic_specialty": {"type": "string"},
            "is_safety_critical": {"type": "boolean"},
            "recommended_action": {"type": "string",
                                   "description": "Brief repair guidance for mechanic"},
            "estimated_downtime_hours": {"type": "number"},
            "parts_likely_needed": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["description", "priority", "is_safety_critical"],
    },
}


def generate_work_order(alert_text: str, equipment_id: str,
                        equipment_desc: str, job_number: str = "",
                        requested_by: str = "FieldBridge") -> dict:
    """
    Convert a telematics alert or fault description into a Vista work order payload.

    alert_text: raw fault/alert text (e.g. "Engine coolant temp high - 240°F threshold exceeded")
    equipment_id: Vista equipment code (emem.Equipment)
    equipment_desc: equipment description for context
    job_number: current job the equipment is assigned to
    requested_by: foreman name or "FieldBridge" for automated alerts

    Returns dict ready for vista_sync.create_work_order().
    """
    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=[{"type": "text", "text": _SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        tools=[_WO_TOOL],
        tool_choice={"type": "tool", "name": "create_work_order"},
        messages=[{
            "role": "user",
            "content": (
                f"Equipment: {equipment_id} — {equipment_desc}\n"
                f"Job: {job_number or 'Not assigned'}\n"
                f"Alert: {alert_text}\n"
                f"Requested by: {requested_by}"
            ),
        }],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "create_work_order":
            result = block.input
            result["equipment"] = equipment_id
            result["job_number"] = job_number
            result["requested_by"] = requested_by
            return result

    return {
        "equipment": equipment_id,
        "description": f"Alert: {alert_text[:55]}",
        "priority": "3",
        "is_safety_critical": False,
        "requested_by": requested_by,
        "job_number": job_number,
    }


def process_telematics_batch(alerts: list[dict]) -> list[dict]:
    """
    Process a batch of telematics alerts → list of work order payloads.

    Each alert dict: {equipment_id, equipment_desc, alert_text, job_number}
    """
    return [
        generate_work_order(
            alert_text=a["alert_text"],
            equipment_id=a["equipment_id"],
            equipment_desc=a.get("equipment_desc", ""),
            job_number=a.get("job_number", ""),
        )
        for a in alerts
    ]
