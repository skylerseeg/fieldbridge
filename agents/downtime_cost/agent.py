"""
Downtime Cost Modeling Agent  (Phase 2 — Turn Data into Dollars)
Converts equipment downtime events from Vista into dollar impact on job cost.
The industry tracks utilization %. We show the actual dollar loss in Vista terms.
"""
import json
from datetime import date
import anthropic

client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-20250514"

_SYSTEM_PROMPT = """
You are a construction equipment cost analyst for VanCon Inc., a heavy civil contractor.

Your job: given equipment downtime records and Vista job cost data, calculate
the REAL dollar impact of each downtime event and produce a clear cost report.

Calculation methodology:
1. Owned equipment downtime cost = (internal billing rate × downtime hours)
   + (labor cost of idle crew waiting) + (job delay cost if on critical path)
2. Rental equipment downtime = (daily rental rate × downtime days) — you don't
   own it but you're still paying for it
3. Subcontractor impact: if a sub was waiting, estimate standby cost
4. Revenue impact: if the equipment was on a billed phase, the unearned
   billing is a real opportunity cost

Provide:
- Total downtime cost by equipment unit
- Root cause category: mechanical, operator, parts delay, weather, etc.
- Top 3 most expensive downtime events with narrative
- Trend: is downtime increasing or decreasing over the period?
- Actionable recommendations to reduce downtime cost
"""


def model_downtime_cost(downtime_records: list[dict],
                        job_cost_data: list[dict],
                        equipment_rates: dict[str, float],
                        period_start: str, period_end: str) -> dict:
    """
    Calculate dollar impact of equipment downtime against Vista job cost data.

    downtime_records: from vista_sync.get_equipment_downtime()
    job_cost_data: from vista_sync.get_job_cost() for affected jobs
    equipment_rates: {equipment_id: internal_billing_rate_per_hour}
    period_start / period_end: date strings for report header

    Returns structured cost report with totals, rankings, and recommendations.
    """
    context = {
        "period": f"{period_start} to {period_end}",
        "downtime_events": downtime_records,
        "job_cost_context": job_cost_data[:20],  # cap tokens
        "equipment_billing_rates": equipment_rates,
    }

    response = client.messages.create(
        model=MODEL,
        max_tokens=3000,
        system=[{"type": "text", "text": _SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{
            "role": "user",
            "content": (
                f"Calculate the downtime cost impact for this period.\n\n"
                f"Data:\n{json.dumps(context, indent=2, default=str)}\n\n"
                "Return a JSON object with: total_downtime_cost, "
                "by_equipment (list with equipment, hours, cost, root_cause), "
                "top_3_events (list with narrative), trend, "
                "recommendations (list), period_summary (string)."
            ),
        }],
    )

    text = response.content[0].text
    import re
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return {
        "total_downtime_cost": 0,
        "by_equipment": [],
        "top_3_events": [],
        "trend": "insufficient data",
        "recommendations": [],
        "period_summary": text,
    }


def quick_downtime_cost(equipment_id: str, downtime_hours: float,
                        billing_rate: float, job_number: str = "") -> float:
    """Fast calculation: downtime hours × billing rate. No AI needed."""
    return round(downtime_hours * billing_rate, 2)
