"""contractors — canonical contractor entities resolved from
``bid_results.contractor_name`` variants.

Resolution pipeline (services/market_intel/normalizers/contractor_resolver):
  1. Strip whitespace, collapse case, drop legal-entity suffixes
     (Inc, LLC, Co, DBA, etc.).
  2. RapidFuzz token_set_ratio against existing canonical_name and
     name_variants. Threshold 92.
  3. If no match, create new canonical row with the first observed
     variant.
  4. Best-effort match to ``apvend`` (Vista vendor master) so VanCon
     can see "this competitor is also one of our vendors / subs".

apvend match runs nightly — it can fail gracefully (apvend_match_id
NULL) without blocking ingest.

Tenant scope: contractors live on the shared-network tenant by
default. Per-tenant overrides (custom canonical names, manual apvend
mappings) are a v3 follow-on; not modeled today.
"""
from __future__ import annotations

import uuid
from sqlalchemy import (
    ARRAY,
    CHAR,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Contractor(Base):
    """Canonical contractor entity, identified by canonical_name."""

    __tablename__ = "contractors"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "canonical_name",
            name="uq_contractors_tenant_name",
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

    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    name_variants: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text),
        # All raw bidder strings observed for this canonical entity.
        # Searched first on resolution; new variants appended.
    )

    headquarters_state: Mapped[str | None] = mapped_column(CHAR(2))
    apvend_match_id: Mapped[str | None] = mapped_column(
        String(40),
        # FK-by-convention into Vista apvend.Vendor. Not a hard FK
        # because Vista lives in a different DB; matched via the
        # services/vista_sync/apvend_matcher resolver.
    )

    # Rolling counters maintained by the analytics layer
    win_count: Mapped[int] = mapped_column(Integer, default=0)
    bid_count: Mapped[int] = mapped_column(Integer, default=0)
    median_bid: Mapped[float | None] = mapped_column(Numeric(14, 2))

    def __repr__(self) -> str:
        return f"<Contractor {self.canonical_name}>"
