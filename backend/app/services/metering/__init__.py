"""
Usage metering service — records Claude API token consumption per tenant.
Called by every agent after each API call to track cost attribution.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timezone, date
from app.models.usage import UsageEvent, calculate_cost

log = logging.getLogger("fieldbridge.metering")


async def record_usage(
    db: AsyncSession,
    tenant_id: str,
    agent: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    model: str = "claude-sonnet-4-20250514",
    job_number: str = "",
    equipment_id: str = "",
    user_id: str | None = None,
) -> UsageEvent:
    """Record a Claude API usage event for a tenant."""
    cost = calculate_cost(input_tokens, output_tokens,
                          cache_read_tokens, cache_write_tokens)
    event = UsageEvent(
        tenant_id=tenant_id,
        agent=agent,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        cost_usd=cost,
        job_number=job_number,
        equipment_id=equipment_id,
        user_id=user_id,
    )
    db.add(event)
    await db.commit()
    log.debug(f"Metered {agent} for {tenant_id}: "
              f"{input_tokens}in/{output_tokens}out = ${cost:.4f}")
    return event


async def get_tenant_usage_summary(
    db: AsyncSession,
    tenant_id: str,
    month: date | None = None,
) -> dict:
    """
    Monthly usage summary for a tenant — total tokens, cost, breakdown by agent.
    Used in the admin dashboard and tenant billing view.
    """
    if month is None:
        month = date.today().replace(day=1)

    month_start = datetime(month.year, month.month, 1, tzinfo=timezone.utc)
    if month.month == 12:
        next_month = datetime(month.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month = datetime(month.year, month.month + 1, 1, tzinfo=timezone.utc)

    # Total cost this month
    total_result = await db.execute(
        select(func.sum(UsageEvent.cost_usd))
        .where(UsageEvent.tenant_id == tenant_id)
        .where(UsageEvent.created_at >= month_start)
        .where(UsageEvent.created_at < next_month)
    )
    total_cost = float(total_result.scalar() or 0)

    # By agent
    by_agent_result = await db.execute(
        select(
            UsageEvent.agent,
            func.sum(UsageEvent.input_tokens).label("input_tokens"),
            func.sum(UsageEvent.output_tokens).label("output_tokens"),
            func.sum(UsageEvent.cost_usd).label("cost_usd"),
            func.count(UsageEvent.id).label("call_count"),
        )
        .where(UsageEvent.tenant_id == tenant_id)
        .where(UsageEvent.created_at >= month_start)
        .where(UsageEvent.created_at < next_month)
        .group_by(UsageEvent.agent)
        .order_by(func.sum(UsageEvent.cost_usd).desc())
    )

    by_agent = [
        {
            "agent": row.agent,
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "cost_usd": round(float(row.cost_usd), 4),
            "call_count": row.call_count,
        }
        for row in by_agent_result
    ]

    return {
        "tenant_id": tenant_id,
        "month": month.strftime("%Y-%m"),
        "total_cost_usd": round(total_cost, 4),
        "by_agent": by_agent,
        "total_calls": sum(a["call_count"] for a in by_agent),
    }


async def get_all_tenants_usage(
    db: AsyncSession,
    month: date | None = None,
) -> list[dict]:
    """Admin view: usage summary across all tenants for a month."""
    if month is None:
        month = date.today().replace(day=1)

    month_start = datetime(month.year, month.month, 1, tzinfo=timezone.utc)
    if month.month == 12:
        next_month = datetime(month.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month = datetime(month.year, month.month + 1, 1, tzinfo=timezone.utc)

    result = await db.execute(
        select(
            UsageEvent.tenant_id,
            func.sum(UsageEvent.cost_usd).label("total_cost"),
            func.sum(UsageEvent.input_tokens).label("total_input"),
            func.sum(UsageEvent.output_tokens).label("total_output"),
            func.count(UsageEvent.id).label("total_calls"),
        )
        .where(UsageEvent.created_at >= month_start)
        .where(UsageEvent.created_at < next_month)
        .group_by(UsageEvent.tenant_id)
        .order_by(func.sum(UsageEvent.cost_usd).desc())
    )

    return [
        {
            "tenant_id": row.tenant_id,
            "total_cost_usd": round(float(row.total_cost), 4),
            "total_input_tokens": row.total_input,
            "total_output_tokens": row.total_output,
            "total_calls": row.total_calls,
            "month": month.strftime("%Y-%m"),
        }
        for row in result
    ]
