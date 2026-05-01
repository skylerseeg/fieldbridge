"""pipeline_runs — operational ledger of every Market Intel pipeline
invocation (ITD scrape, Excel mart ingest, NAPC probe, future state-DOT
scrapers, etc.).

Phase 2 will populate this. Phase 1 (this PR) creates the table so
``bid_events.pipeline_run_id`` and ``bid_results.pipeline_run_id``
have a valid FK target. Empty rows are fine — the existing pipeline
code is unchanged in this PR.

Once populated, the row drives:
  * Operator "last successful run" banner in the UI.
  * Per-run debugging — which run produced which set of bids.
  * Counter rollups for Render alerting (consecutive failures, drift
    in row counts, etc.).

Tenant scope: a run can be customer-scoped (Excel ingest for VanCon)
or shared-network-scoped (ITD scrape writes under
SHARED_NETWORK_TENANT_ID). Either way, ``tenant_id`` records the row
the pipeline wrote AGAINST, not the operator who triggered it.

See ``docs/market-intel-data-state.md`` § 6d.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PipelineRun(Base):
    """One row per pipeline invocation."""

    __tablename__ = "pipeline_runs"
    __table_args__ = (
        # "Show me the last N runs of pipeline X" — the most common
        # operational query.
        Index(
            "ix_pipeline_runs_name_started",
            "pipeline_name",
            "started_at",
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

    # Short slug identifying the pipeline:
    #   'itd' | 'excel_ingest' | 'napc_probe' | 'state_dot_ut' | ...
    pipeline_name: Mapped[str] = mapped_column(String(120), nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    # 'running' | 'ok' | 'error' | 'partial'.
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="running",
        server_default="running",
    )

    # Free-form pipeline-specific counter dict. Examples:
    #   ITD: {"discovered": 12, "fetched": 12, "parsed": 11,
    #         "skipped_idempotent": 5, "wrote_events": 6,
    #         "wrote_results": 24}
    counters: Mapped[dict | None] = mapped_column(JSON)

    error_message: Mapped[str | None] = mapped_column(Text)

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
            f"<PipelineRun {self.pipeline_name} "
            f"{self.status} {self.started_at}>"
        )
