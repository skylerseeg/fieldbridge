"""
Safety Agent  (Domain 7)
Safety scorecard, incident/near-miss logging, and maintenance-feedback loop.
Tenna has the scorecard but it's hardware-dependent. Nobody logs near-misses
back into equipment maintenance decisions — FieldBridge does.
"""
import json
from datetime import datetime, date
import anthropic

client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-20250514"

_SYSTEM_PROMPT = """
You are a construction safety manager for VanCon Inc., a heavy civil contractor.

You manage:
1. SAFETY SCORECARD: Calculate EMR-aligned safety metrics across active jobs.
   Thresholds: DART rate <2.0 = green, 2.0-4.0 = yellow, >4.0 = red.
   TRIR <3.0 = green, 3.0-6.0 = yellow, >6.0 = red.
2. INCIDENT ANALYSIS: Classify incidents (OSHA recordable, first aid, near-miss),
   identify root cause, and determine if any equipment maintenance action is needed.
3. EQUIPMENT FEEDBACK: When an incident involves equipment malfunction,
   generate a work order recommendation. This is the loop nobody else closes.
4. TRENDING: Identify patterns — same equipment, same crew, same conditions.

For every incident involving equipment:
- Flag if the equipment should be taken out of service
- Generate maintenance work order recommendation with priority
- Note if telematics data should be reviewed for precursor signals
"""

_INCIDENT_TOOL = {
    "name": "classify_incident",
    "description": "Classify a safety incident and generate follow-up actions",
    "input_schema": {
        "type": "object",
        "properties": {
            "incident_type": {"type": "string",
                              "enum": ["recordable", "first_aid", "near_miss",
                                       "property_damage", "environmental"]},
            "osha_classification": {"type": "string",
                                    "enum": ["fatality", "hospitalization",
                                             "lost_time", "restricted_duty",
                                             "medical_treatment", "first_aid",
                                             "near_miss", "not_recordable"]},
            "root_cause": {"type": "string"},
            "contributing_factors": {"type": "array", "items": {"type": "string"}},
            "equipment_involved": {"type": "string"},
            "equipment_work_order_needed": {"type": "boolean"},
            "work_order_description": {"type": "string"},
            "work_order_priority": {"type": "string", "enum": ["1", "2", "3"]},
            "take_equipment_offline": {"type": "boolean"},
            "corrective_actions": {"type": "array", "items": {"type": "string"}},
            "review_telematics": {"type": "boolean"},
            "regulatory_reporting_required": {"type": "boolean"},
            "reporting_deadline_hours": {"type": "integer"},
        },
        "required": ["incident_type", "osha_classification", "root_cause",
                     "equipment_work_order_needed", "corrective_actions"],
    },
}


def log_incident(description: str, date_of_incident: str,
                 job_number: str, employee_id: str,
                 equipment_id: str = "",
                 witness_statements: list[str] | None = None) -> dict:
    """
    Classify and log a safety incident. Generates maintenance actions if equipment involved.

    Returns incident record with OSHA classification, root cause, and follow-up actions.
    """
    context = (
        f"Date: {date_of_incident}\n"
        f"Job: {job_number}\n"
        f"Employee: {employee_id}\n"
        f"Equipment involved: {equipment_id or 'None'}\n"
        f"Description: {description}\n"
    )
    if witness_statements:
        context += f"Witness statements:\n" + "\n".join(f"- {s}" for s in witness_statements)

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=[{"type": "text", "text": _SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        tools=[_INCIDENT_TOOL],
        tool_choice={"type": "tool", "name": "classify_incident"},
        messages=[{"role": "user", "content": context}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "classify_incident":
            result = block.input
            result.update({
                "job_number": job_number,
                "employee_id": employee_id,
                "equipment_id": equipment_id,
                "date_of_incident": date_of_incident,
                "logged_at": datetime.utcnow().isoformat(),
                "description": description,
            })
            return result

    return {
        "incident_type": "near_miss",
        "osha_classification": "not_recordable",
        "root_cause": "Manual review required",
        "equipment_work_order_needed": bool(equipment_id),
        "corrective_actions": ["Review incident manually"],
        "job_number": job_number,
        "logged_at": datetime.utcnow().isoformat(),
    }


def calculate_safety_scorecard(incidents: list[dict],
                                total_hours_worked: float,
                                active_jobs: list[str]) -> dict:
    """
    Calculate safety scorecard metrics.

    incidents: list of logged incidents (from log_incident or stored records)
    total_hours_worked: total labor hours in the period (from Vista preh)
    active_jobs: list of active job numbers

    Returns TRIR, DART rate, incident summary, and status flags.
    """
    recordable = [i for i in incidents
                  if i.get("osha_classification") not in ("first_aid", "near_miss",
                                                            "not_recordable")]
    dart_cases = [i for i in incidents
                  if i.get("osha_classification") in ("lost_time", "restricted_duty",
                                                        "hospitalization", "fatality")]
    near_misses = [i for i in incidents if i.get("incident_type") == "near_miss"]

    hours = total_hours_worked or 1  # avoid division by zero
    trir = round((len(recordable) * 200000) / hours, 2)
    dart = round((len(dart_cases) * 200000) / hours, 2)

    return {
        "period_hours": total_hours_worked,
        "total_incidents": len(incidents),
        "recordable_count": len(recordable),
        "dart_cases": len(dart_cases),
        "near_miss_count": len(near_misses),
        "trir": trir,
        "dart_rate": dart,
        "trir_status": "green" if trir < 3.0 else "yellow" if trir < 6.0 else "red",
        "dart_status": "green" if dart < 2.0 else "yellow" if dart < 4.0 else "red",
        "active_jobs": active_jobs,
        "equipment_flags": [i for i in incidents if i.get("take_equipment_offline")],
    }
