"""
Usage metering — tracks Claude API token consumption per tenant per agent.
Used for billing tier validation and cost attribution.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Integer, Float, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                     default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36),
                                            ForeignKey("tenants.id", ondelete="CASCADE"),
                                            nullable=False, index=True)
    # Which agent generated this usage
    agent: Mapped[str] = mapped_column(String(60), nullable=False)
    # e.g. job_cost_coding, work_order_sync, media_agent, etc.

    model: Mapped[str] = mapped_column(String(60), default="claude-sonnet-4-20250514")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)

    # Computed cost in USD (calculated at insert time)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    # Optional: which Vista entity triggered this call
    job_number: Mapped[str] = mapped_column(String(20), default="")
    equipment_id: Mapped[str] = mapped_column(String(20), default="")
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True)

    tenant: Mapped["Tenant"] = relationship("Tenant",  # noqa: F821
                                             back_populates="usage_events")

    __table_args__ = (
        Index("ix_usage_tenant_created", "tenant_id", "created_at"),
        Index("ix_usage_tenant_agent", "tenant_id", "agent"),
    )


# Claude pricing constants (per million tokens)
SONNET_INPUT_PRICE = 3.00
SONNET_OUTPUT_PRICE = 15.00
SONNET_CACHE_READ_PRICE = 0.30
SONNET_CACHE_WRITE_PRICE = 3.75


def calculate_cost(input_tokens: int, output_tokens: int,
                   cache_read_tokens: int = 0,
                   cache_write_tokens: int = 0) -> float:
    """Calculate USD cost for a Claude API call."""
    cost = (
        (input_tokens / 1_000_000) * SONNET_INPUT_PRICE +
        (output_tokens / 1_000_000) * SONNET_OUTPUT_PRICE +
        (cache_read_tokens / 1_000_000) * SONNET_CACHE_READ_PRICE +
        (cache_write_tokens / 1_000_000) * SONNET_CACHE_WRITE_PRICE
    )
    return round(cost, 6)
