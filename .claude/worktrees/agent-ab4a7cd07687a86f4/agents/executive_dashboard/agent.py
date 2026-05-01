"""
Executive Dashboard Agent  (Phase 3 — Intelligence Layer)
Synthesizes Vista financials + field ops into a one-page executive summary.
Pulls from the Vista pipe already built — just a read layer on top.
"""
import json
import anthropic

client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-20250514"

_SYSTEM_PROMPT = """
You are a CFO-level reporting analyst for VanCon Inc., a heavy civil contractor.

Produce a concise executive dashboard from Vista + field operations data.
The audience is the owner/president/CFO — they have 5 minutes, not 30.

Dashboard sections:
1. FINANCIAL PULSE: Revenue billed this period, cost-to-date vs. budget,
   gross margin trend, top 3 jobs by variance (over/under)
2. FLEET STATUS: Active equipment count, utilization %, top downtime cause,
   fleet P&L summary, critical maintenance items
3. SAFETY: EMR trend, incidents this period, near-misses, open safety items
4. OPERATIONS: Jobs at risk (schedule/cost), upcoming milestones, resource gaps
5. CASH: AR aging, top 3 overdue invoices, upcoming AP obligations
6. AI INSIGHT: One key finding and one recommended action for this week

Format numbers as currency ($1.2M) or percentages. Use plain language.
Flag items red/yellow/green based on thresholds. Keep each section to 3-5 bullet points.
"""


def generate_dashboard(financial_data: dict,
                       fleet_data: dict,
                       safety_data: dict,
                       operations_data: dict,
                       period_label: str = "This Week") -> dict:
    """
    Generate an executive dashboard from aggregated Vista data.

    financial_data: job cost summary, billing, margins
    fleet_data: utilization, downtime, P&L summary
    safety_data: incidents, EMR, open items
    operations_data: job status, milestones, resource summary
    period_label: display label for the period

    Returns structured dashboard dict with status flags.
    """
    context = {
        "period": period_label,
        "financials": financial_data,
        "fleet": fleet_data,
        "safety": safety_data,
        "operations": operations_data,
    }

    response = client.messages.create(
        model=MODEL,
        max_tokens=3000,
        system=[{"type": "text", "text": _SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{
            "role": "user",
            "content": (
                f"Generate the executive dashboard for {period_label}.\n\n"
                f"{json.dumps(context, indent=2, default=str)}\n\n"
                "Return JSON with sections: financial_pulse, fleet_status, "
                "safety, operations, cash, ai_insight. Each section: "
                "status (green/yellow/red), bullets (list of strings), "
                "key_metric (string). Plus: generated_at, period."
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
        "period": period_label,
        "financial_pulse": {"status": "yellow", "bullets": [], "key_metric": ""},
        "fleet_status": {"status": "yellow", "bullets": [], "key_metric": ""},
        "safety": {"status": "green", "bullets": [], "key_metric": ""},
        "operations": {"status": "yellow", "bullets": [], "key_metric": ""},
        "cash": {"status": "yellow", "bullets": [], "key_metric": ""},
        "ai_insight": {"status": "yellow", "bullets": [text[:500]], "key_metric": ""},
    }
