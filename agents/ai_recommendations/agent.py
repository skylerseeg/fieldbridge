"""
AI Recommendations Agent  (Phase 3 — Intelligence Layer)
Synthesizes data from all Vista domains to generate proactive, prioritized
action recommendations. Turns raw data into decisions.
"""
import json
import anthropic

client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-20250514"

_SYSTEM_PROMPT = """
You are a senior operations advisor for VanCon Inc., a heavy civil contractor.

Analyze operational data and generate prioritized recommendations that drive
real business outcomes: reduce cost, improve margins, avoid risk, win more work.

Recommendation types:
- MAINTENANCE: Equipment needing attention before failure
- COST: Job cost overruns, billing gaps, unbilled work
- SAFETY: Incidents, near-misses, equipment safety flags
- UTILIZATION: Idle equipment, under-billed assets, rental vs. own opportunities
- CASH_FLOW: AP/AR timing, invoice aging, retention releases
- OPERATIONS: Scheduling conflicts, resource gaps, subcontractor performance
- COMPLIANCE: Payroll coding errors, certified payroll, prevailing wage

Each recommendation must:
1. State the specific finding (not a generic observation)
2. Quantify the dollar impact where possible
3. Give a specific action with a deadline
4. Name who is responsible
5. Rate priority: P1 (act today), P2 (this week), P3 (this month)

Never give generic advice. Every recommendation must be grounded in the data provided.
"""


def generate_recommendations(data_snapshot: dict) -> list[dict]:
    """
    Generate prioritized operational recommendations from Vista data.

    data_snapshot: aggregated dict with keys like:
      - open_work_orders: list
      - job_cost_variances: list (jobs over budget)
      - pm_overdue: list
      - utilization_summary: dict
      - payroll_flags: list
      - downtime_summary: dict
      - safety_incidents: list

    Returns sorted list of recommendations (P1 first).
    """
    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=[{"type": "text", "text": _SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{
            "role": "user",
            "content": (
                f"Generate operational recommendations from this data snapshot.\n\n"
                f"{json.dumps(data_snapshot, indent=2, default=str)}\n\n"
                "Return a JSON array. Each recommendation: "
                "type, priority (P1/P2/P3), title (≤80 chars), "
                "finding, dollar_impact (number or null), "
                "action, deadline, responsible_party, "
                "supporting_data (brief list of facts from the input)."
            ),
        }],
    )

    text = response.content[0].text
    import re
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            recs = json.loads(match.group(0))
            priority_order = {"P1": 0, "P2": 1, "P3": 2}
            return sorted(recs, key=lambda x: priority_order.get(x.get("priority", "P3"), 3))
        except json.JSONDecodeError:
            pass

    return []
