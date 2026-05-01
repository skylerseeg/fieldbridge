"""
Predictive Maintenance Agent  (Phase 3 — Intelligence Layer)
Analyzes Vista equipment history + telematics patterns to predict failures
before they cause unplanned downtime. Goes beyond Clue's fault-code matching.
"""
import json
import anthropic

client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-20250514"

_SYSTEM_PROMPT = """
You are a predictive maintenance engineer for VanCon Inc.'s heavy civil equipment fleet.

Analyze equipment history to identify failure risk BEFORE breakdown occurs.

Pattern recognition:
- PM overdue + high-utilization = elevated risk
- Repeat work orders on same system (hydraulics, engine, drive) = systemic issue
- Hour meter approaching manufacturer service intervals
- Seasonal patterns: summer heat stress on cooling systems, winter cold starts
- Age + hours = cumulative wear curves

Risk scoring:
- Critical (>80%): Failure likely within 1-2 weeks — take offline for inspection
- High (60-80%): Schedule repair within 2 weeks
- Medium (40-60%): Monitor closely, schedule next PM earlier
- Low (<40%): Normal operation, follow standard PM schedule

For each alert, provide:
1. Component at risk and failure mode
2. Supporting evidence from history
3. Recommended action with urgency
4. Estimated cost to prevent vs. cost if it fails (use industry failure costs)
5. Suggested parts to pre-order

Heavy civil failure cost benchmarks:
- Engine failure (excavator/dozer): $25,000-80,000 repair + 2-4 weeks downtime
- Hydraulic pump failure: $8,000-25,000 + 1-2 weeks downtime
- Final drive failure (excavator): $15,000-40,000 + 2-3 weeks downtime
- Transmission failure (ADT/motor grader): $20,000-60,000 + 2-4 weeks downtime
"""


def predict_failures(equipment_history: list[dict],
                     pm_schedule: list[dict],
                     telematics_alerts: list[dict] | None = None,
                     *,
                     return_usage: bool = False):
    """
    Analyze equipment maintenance history to predict upcoming failures.

    equipment_history: work orders from vista_sync.get_work_orders()
    pm_schedule: equipment master data with PM intervals
    telematics_alerts: recent fault codes from GPS/telematics system
    return_usage: when True, returns ``(alerts, usage)`` so callers can
        meter token consumption. ``usage`` is a dict with input_tokens,
        output_tokens, cache_read_tokens, cache_write_tokens.

    Returns list of risk alerts sorted by risk score descending (or a
    tuple ``(list, usage)`` when ``return_usage=True``).
    """
    context = {
        "work_order_history": equipment_history[:50],
        "pm_schedule": pm_schedule,
        "recent_telematics": telematics_alerts or [],
    }

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=[{"type": "text", "text": _SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{
            "role": "user",
            "content": (
                f"Analyze this equipment data for failure risk.\n\n"
                f"{json.dumps(context, indent=2, default=str)}\n\n"
                "Return a JSON array of risk alerts. Each alert: "
                "equipment_id, equipment_desc, risk_score (0-100), "
                "risk_level (Critical/High/Medium/Low), component_at_risk, "
                "failure_mode, evidence (list), recommended_action, "
                "urgency_days, prevention_cost_estimate, "
                "failure_cost_estimate, parts_to_preorder (list)."
            ),
        }],
    )

    text = response.content[0].text
    alerts: list[dict] = []
    import re
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            alerts = sorted(
                json.loads(match.group(0)),
                key=lambda x: x.get("risk_score", 0),
                reverse=True,
            )
        except json.JSONDecodeError:
            alerts = []

    if not return_usage:
        return alerts

    usage = {
        "input_tokens": getattr(response.usage, "input_tokens", 0),
        "output_tokens": getattr(response.usage, "output_tokens", 0),
        "cache_read_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        "cache_write_tokens": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
    }
    return alerts, usage


def check_pm_overdue(equipment_master: list[dict]) -> list[dict]:
    """
    Fast check: which equipment has overdue or upcoming PMs based on
    HourMeter vs NextPMHours from Vista emem. No Claude call needed.
    """
    overdue = []
    for eq in equipment_master:
        current_hours = float(eq.get("HourMeter", 0) or 0)
        next_pm = float(eq.get("NextPMHours", 0) or 0)
        if next_pm <= 0:
            continue
        hours_until_pm = next_pm - current_hours
        if hours_until_pm <= 0:
            status = "OVERDUE"
        elif hours_until_pm <= 50:
            status = "DUE_SOON"
        else:
            continue
        overdue.append({
            "equipment": eq.get("Equipment"),
            "description": eq.get("Description"),
            "current_hours": current_hours,
            "next_pm_hours": next_pm,
            "hours_until_pm": hours_until_pm,
            "status": status,
        })
    return sorted(overdue, key=lambda x: x["hours_until_pm"])
