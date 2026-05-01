"""
Fleet P&L Agent  (Phase 2 — Turn Data into Dollars)
Calculates profit and loss by equipment asset class using Vista job cost data.
Answers: which equipment is making money, which is a drain, and what to do about it.
"""
import json
from datetime import date
import anthropic

client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-20250514"

_SYSTEM_PROMPT = """
You are a construction equipment financial analyst for VanCon Inc.

Calculate fleet P&L using Vista data. For each equipment unit/class:
- Revenue: billing rate × billed hours from job cost (jcjm/jcci)
- Direct costs: parts (emwo.PartsCost), labor (preh hours × rate), fuel estimate
- Overhead allocation: insurance, depreciation, licensing (use industry standards
  if not provided: ~15% of replacement cost annually)
- Net P&L per unit and per category

Asset classes for heavy civil:
- Excavators (EX): $180-250/hr billing
- Dozers (D): $150-200/hr billing
- Motor Graders (GR): $160-220/hr billing
- Scrapers (SC): $200-280/hr billing
- Haul Trucks (TR): $80-120/hr billing
- Compactors (CP): $100-150/hr billing
- Cranes/Picker (CR): $250-400/hr billing
- Support (pumps, generators, misc): $40-80/hr billing

Provide:
- P&L table by unit, subtotaled by class
- Top 3 profit contributors and bottom 3 loss leaders
- Buy/rent/retire recommendations for underperforming units
- Overall fleet P&L margin
"""


def calculate_fleet_pl(utilization_data: list[dict],
                       work_order_costs: list[dict],
                       equipment_master: list[dict],
                       period_start: str, period_end: str) -> dict:
    """
    Calculate fleet P&L for a period.

    utilization_data: from vista_sync.get_equipment_utilization()
    work_order_costs: from vista_sync.get_work_orders() (closed WOs with costs)
    equipment_master: from vista_sync.get_equipment() (for category/rates)
    period_start / period_end: date strings

    Returns P&L report with by-unit breakdown and strategic recommendations.
    """
    context = {
        "period": f"{period_start} to {period_end}",
        "utilization": utilization_data,
        "maintenance_costs": work_order_costs[:50],  # closed WOs
        "equipment_master": equipment_master[:100],
    }

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=[{"type": "text", "text": _SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{
            "role": "user",
            "content": (
                f"Calculate fleet P&L for this period.\n\n"
                f"Data:\n{json.dumps(context, indent=2, default=str)}\n\n"
                "Return JSON with: period, total_fleet_revenue, total_fleet_cost, "
                "net_pl, margin_pct, by_unit (list), by_class (list), "
                "top_performers (list of 3), bottom_performers (list of 3), "
                "buy_rent_retire_recommendations (list), executive_summary (string)."
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
        "period": f"{period_start} to {period_end}",
        "total_fleet_revenue": 0,
        "total_fleet_cost": 0,
        "net_pl": 0,
        "margin_pct": 0,
        "by_unit": [],
        "by_class": [],
        "top_performers": [],
        "bottom_performers": [],
        "buy_rent_retire_recommendations": [],
        "executive_summary": text,
    }
