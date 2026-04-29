"""bid_events — public bid solicitation/award records scraped from
state networks (NAPC, state DOTs) plus VanCon-internal bid history
when Vista bid tracking is incomplete.

Tenant scoping: every row belongs to a tenant. The shared bid network
is a tenant of kind=shared_dataset (slug ``shared-network``) seeded by
``app/core/seed.py``. Customer-tenant queries union their own tenant_id
with the shared sentinel — pattern used by ``mart_vendor_enrichments``
overlay tables.

Owned by Market Intel (v1.5). See ``docs/market-intel.md`` for the
full design.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from sqlalchemy import (
    ARRAY,
    CHAR,
    DateTime,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class BidEvent(Base):
    """One bid solicitation (open) or award (closed). Sourced from
    NAPC state portals first; state-DOT bid tab parsers in v1.5b."""

    __tablename__ = "bid_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_url",
            "raw_html_hash",
            name="uq_bid_events_source",
        ),
        Index(
            "ix_bid_events_tenant_state_date",
            "tenant_id",
            "location_state",
            "bid_open_date",
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

    # Provenance
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_state: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    source_network: Mapped[str] = mapped_column(
        String(40), nullable=False,
        # 'napc' | 'bidnet' | 'state_dot_ut' | 'state_dot_id' | ...
    )
    solicitation_id: Mapped[str | None] = mapped_column(String(120))
    raw_html_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)

    # Project
    project_title: Mapped[str] = mapped_column(Text, nullable=False)
    project_owner: Mapped[str | None] = mapped_column(Text)
    work_scope: Mapped[str | None] = mapped_column(Text)
    csi_codes: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(8)),
        # 4-digit Vista CSI format, inferred via shared keyword map
        # in services/email_bridge/csi_inference. Multiple per project.
    )

    # Timeline
    bid_open_date: Mapped[date | None] = mapped_column(Date, index=True)
    bid_status: Mapped[str | None] = mapped_column(
        String(20),
        # 'open' | 'closed' | 'awarded' | 'cancelled'
    )

    # Geography
    location_city: Mapped[str | None] = mapped_column(String(120))
    location_county: Mapped[str | None] = mapped_column(String(120))
    location_state: Mapped[str | None] = mapped_column(CHAR(2), index=True)

    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    results: Mapped[list["BidResult"]] = relationship(  # noqa: F821
        "BidResult",
        back_populates="event",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<BidEvent {self.source_state} "
            f"{self.bid_open_date} {self.project_title[:40]}>"
        )
