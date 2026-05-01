"""bid_results — one row per bidder per bid event.

The competitor-curve and win-calibration analytics live entirely on
this table joined back to ``bid_events``. Rank 1 is the low bidder;
``is_low_bidder`` is denormalized for fast indexed reads.

Layer B forward-compat (Phase 1): adds ``listed_subs``,
``listed_suppliers``, ``bond_amount``, ``is_disqualified``,
``pct_above_low``, ``pipeline_run_id``, ``created_at``, ``updated_at``.
See ``docs/market-intel-data-state.md`` § 6b.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
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

    # ---- Layer B forward-compat (Phase 1) -----------------------------------
    # Percent above the low bid for this event.
    #
    # Formula (computed in app code on insert):
    #     (bid_amount - low_bid_amount) / low_bid_amount
    #
    # Postgres generated columns are not portable to SQLite, so we
    # compute on write rather than declare ``Computed(...)``. NULL
    # when ``bid_amount`` or the event's low bid is unknown. The low
    # bidder gets 0.
    pct_above_low: Mapped[float | None] = mapped_column(Numeric(6, 4))
    # True when the bid was thrown out for non-responsiveness, late
    # submission, missing bond, etc. ``server_default=text("FALSE")``
    # works on both Postgres (case-insensitive) and SQLite (uppercase
    # string literal accepted as boolean false).
    is_disqualified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("FALSE"),
    )
    # Bond amount submitted with the bid (when published).
    bond_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    # List of subcontractors listed on this bid:
    #     [{"name": str, "scope": str, "amount": float,
    #       "csi_code": str, "used": bool}, ...]
    # ``used`` distinguishes "sub we got a quote from" vs. "sub we
    # actually used in the submitted bid".
    # JSON not ARRAY for cross-dialect portability (see bid_event.csi_codes).
    listed_subs: Mapped[list[dict] | None] = mapped_column(JSON)
    # List of material suppliers listed on this bid:
    #     [{"name": str, "material": str, "amount": float,
    #       "csi_code": str, "used": bool}, ...]
    listed_suppliers: Mapped[list[dict] | None] = mapped_column(JSON)
    # FK to the pipeline run that wrote this row. NULL on rows written
    # before pipeline_runs existed.
    pipeline_run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("pipeline_runs.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        onupdate=func.now(),
        nullable=False,
    )
    # ------------------------------------------------------------------------

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
