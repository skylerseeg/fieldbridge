"""bid_results — one row per bidder per bid event.

The competitor-curve and win-calibration analytics live entirely on
this table joined back to ``bid_events``. Rank 1 is the low bidder;
``is_low_bidder`` is denormalized for fast indexed reads.
"""
from __future__ import annotations

import uuid
from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class BidResult(Base):
    """A single bidder's submission on one ``BidEvent``."""

    __tablename__ = "bid_results"
    __table_args__ = (
        UniqueConstraint(
            "bid_event_id",
            "contractor_name",
            name="uq_bid_results_event_contractor",
        ),
        Index(
            "ix_bid_results_tenant_contractor",
            "tenant_id",
            "contractor_name",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bid_event_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("bid_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    contractor_name: Mapped[str] = mapped_column(Text, nullable=False)
    contractor_url: Mapped[str | None] = mapped_column(Text)
    bid_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))

    is_low_bidder: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    is_awarded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    rank: Mapped[int | None] = mapped_column(Integer)
    # rank=1 is the low bidder. NULL when only the low is published.

    event: Mapped["BidEvent"] = relationship(  # noqa: F821
        "BidEvent",
        back_populates="results",
        lazy="joined",
    )

    def __repr__(self) -> str:
        return (
            f"<BidResult #{self.rank} {self.contractor_name} "
            f"${self.bid_amount}>"
        )
