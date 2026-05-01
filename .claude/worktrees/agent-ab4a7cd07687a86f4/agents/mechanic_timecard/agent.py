"""
Mechanic Timecard Agent  (Phase 1 — Vista Pipe)
Parses raw mechanic timecard submissions (text/photo/form) and maps them
to Vista preh payroll records. Eliminates manual re-entry and coding errors.
"""
import json
import anthropic

client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-20250514"

_SYSTEM_PROMPT = """
You are a payroll coding specialist for VanCon Inc., a heavy civil contractor.

Parse mechanic timecard data and return Vista preh-ready payroll records.

Vista cost types for labor:
- L1: Regular time (straight pay)
- L2: Overtime (1.5x)
- L3: Double time (2x)
- L4: Standby / travel

Phase codes for shop/maintenance work:
- 9900: Shop — General Maintenance
- 9910: Shop — Preventive Maintenance
- 9920: Shop — Breakdown Repair
- 9930: Shop — Fabrication/Modification
- 9940: Travel / Transport

Rules:
- Hours >8 in a day = overtime for remaining hours (union scale)
- Hours >10 = double time beyond 10 (check state rules — default CA)
- Always split regular/OT/DT into separate preh records
- Charge to the job/WO being worked, not the shop general
- Flag missing WO references for review
"""

_TIMECARD_TOOL = {
    "name": "parse_timecard",
    "description": "Parse mechanic timecard into Vista preh payroll records",
    "input_schema": {
        "type": "object",
        "properties": {
            "records": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "employee": {"type": "string"},
                        "week_ending": {"type": "string", "description": "YYYY-MM-DD"},
                        "job_number": {"type": "string"},
                        "phase": {"type": "string"},
                        "cost_type": {"type": "string"},
                        "hours": {"type": "number"},
                        "pay_rate": {"type": "number"},
                        "equipment": {"type": "string", "description": "Equipment worked on"},
                        "work_order": {"type": "string"},
                    },
                    "required": ["employee", "week_ending", "job_number",
                                 "phase", "cost_type", "hours"],
                },
            },
            "total_hours": {"type": "number"},
            "flags": {"type": "array", "items": {"type": "string"},
                      "description": "Issues needing review"},
        },
        "required": ["records", "total_hours"],
    },
}


def parse_timecard(timecard_text: str, employee_id: str,
                   week_ending: str, pay_rate: float = 0.0) -> dict:
    """
    Parse a mechanic's timecard text into Vista preh records.

    timecard_text: raw text (from form, SMS, photo OCR, or typed entry)
    employee_id: Vista employee code
    week_ending: week-ending date string (YYYY-MM-DD)
    pay_rate: base hourly rate (0 = look up from Vista)

    Returns {records: [...], total_hours, flags}
    """
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=[{"type": "text", "text": _SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        tools=[_TIMECARD_TOOL],
        tool_choice={"type": "tool", "name": "parse_timecard"},
        messages=[{
            "role": "user",
            "content": (
                f"Employee: {employee_id}\n"
                f"Week ending: {week_ending}\n"
                f"Base pay rate: ${pay_rate:.2f}/hr\n\n"
                f"Timecard:\n{timecard_text}"
            ),
        }],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "parse_timecard":
            result = block.input
            for rec in result.get("records", []):
                if not rec.get("employee"):
                    rec["employee"] = employee_id
                if not rec.get("pay_rate") and pay_rate:
                    rec["pay_rate"] = pay_rate
            return result

    return {"records": [], "total_hours": 0,
            "flags": ["Parse failed — manual review required"]}


def parse_crew_timecards(timecards: list[dict]) -> list[dict]:
    """
    Parse multiple timecards for a crew.
    Each dict: {employee_id, week_ending, timecard_text, pay_rate}
    Returns flat list of all preh records.
    """
    all_records: list[dict] = []
    for tc in timecards:
        result = parse_timecard(
            timecard_text=tc["timecard_text"],
            employee_id=tc["employee_id"],
            week_ending=tc["week_ending"],
            pay_rate=tc.get("pay_rate", 0.0),
        )
        all_records.extend(result.get("records", []))
    return all_records
