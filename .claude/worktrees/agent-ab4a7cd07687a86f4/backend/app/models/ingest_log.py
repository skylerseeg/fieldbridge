"""
Log of every Excel → mart ingest run, scoped per tenant.
Populated by app.core.ingest.run_ingest().
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class IngestLog(Base):
    __tablename__ = "ingest_log"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_file: Mapped[str] = mapped_column(String(512), nullable=False)
    target_table: Mapped[str] = mapped_column(String(120), nullable=False)

    # ok | partial | error
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    rows_read: Mapped[int] = mapped_column(Integer, default=0)
    rows_written: Mapped[int] = mapped_column(Integer, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, default=0)

    # JSON-encoded list[str], truncated to ~50 entries
    errors: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_ingest_log_tenant_started", "tenant_id", "started_at"),
        Index("ix_ingest_log_tenant_job", "tenant_id", "job_name"),
    )
