"""bid_breakdowns — Layer A foundation: VanCon's internal cost-bucket
breakdown for each bid we submitted.

This is **per-customer-tenant** data. It lives on the customer's own
tenant row and is never written to ``SHARED_NETWORK_TENANT_ID``. The
internal-tenant rule mirrors the design in
``docs/market-intel-data-state.md`` § 6c.

The intended populator is the Vista/HCSS estimate sync once
KWMF-sql.viewpointdata.cloud SQL Auth is provisioned. Until then,
the table is empty (Phase 1 is schema-only) and the Excel mart
``mart_bids_history`` + ``mart_proposal_line_items`` provide the
interim data via the analytics layer.

Join semantics:
  * ``bid_event_id`` is nullable — VanCon may have an internal estimate
    for a bid that we never observed in the public bid record (or the
    public record arrives later via a delayed scrape).
  * ``vista_estimate_id`` is the link back into HCSS / Vista. UNIQUE
    so an estimate can land here exactly once.

See ``docs/market-intel-data-state.md`` § 6c for the design rationale.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BidBreakdown(Base):
    """One internal cost-bucket breakdown per bid we submitted."""

    __tablename__ = "bid_breakdowns"
    __table_args__ = (
        # UNIQUE on vista_estimate_id — an HCSS estimate maps to at
        # most one breakdown row.
        UniqueConstraint(
            "vista_estimate_id",
            name="uq_bid_breakdowns_vista_estimate",
        ),
        # Reverse-lookup index: from a public bid_event back to the
        # internal breakdown (when we have one).
        Index(
            "ix_bid_breakdowns_bid_event",
            "bid_event_id",
        ),
        # Time-series queries scoped to a tenant.
        Index(
            "ix_bid_breakdowns_tenant_estimate_date",
            "tenant_id",
            "estimate_date",
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

    # NULL when we have a VanCon estimate but no matching scraped
    # public bid record (yet, or ever).
    bid_event_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("bid_events.id", ondelete="SET NULL"),
    )

    # The HCSS / Vista estimate identifier. NULL until KWMF-sql
    # access lands. UNIQUE constraint via __table_args__ above.
    vista_estimate_id: Mapped[str | None] = mapped_column(String(120))

    # Required: total submitted bid amount.
    submitted_amount: Mapped[float] = mapped_column(
        Numeric(14, 2), nullable=False,
    )

    # Required: the date the estimate / bid was prepared.
    estimate_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Required: cost-bucket breakdown.
    # Shape: {"labor": float, "materials": float, "equipment": float,
    #         "subs": float, "overhead": float}.
    # Free-form for v1; tighten with a Pydantic model in v2 if the
    # bucket set stabilizes.
    cost_buckets: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Optional: total man-hours estimated.
    man_hours: Mapped[float | None] = mapped_column(Numeric(10, 2))

    # Optional crew composition.
    # Shape: {"operators": int, "laborers": int, "foreman": int, ...}.
    crew_composition: Mapped[dict | None] = mapped_column(JSON)

    # Optional equipment-mix dict.
    # Shape: {"dozer_d6": 200, "excavator_320": 80, ...} (hours).
    equipment_mix: Mapped[dict | None] = mapped_column(JSON)

    # Sub quotes received and used/not-used markers.
    # Shape: [{"sub": str, "scope": str, "amount": float,
    #          "used": bool, "csi_code": str}, ...].
    sub_quotes: Mapped[list[dict] | None] = mapped_column(JSON)

    # Supplier quotes received and used/not-used markers.
    # Shape: [{"supplier": str, "material": str, "amount": float,
    #          "used": bool, "csi_code": str}, ...].
    supplier_quotes: Mapped[list[dict] | None] = mapped_column(JSON)

    # Did VanCon win this bid? Default false; flipped true post-award.
    won: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("FALSE"),
    )

    notes: Mapped[str | None] = mapped_column(Text)

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

    def __repr__(self) -> str:
        return (
            f"<BidBreakdown tenant={self.tenant_id[:8]} "
            f"estimate={self.estimate_date} "
            f"${self.submitted_amount}>"
        )
