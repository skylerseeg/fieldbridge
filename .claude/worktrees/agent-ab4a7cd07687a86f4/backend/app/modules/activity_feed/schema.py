"""Pydantic response models for the activity_feed module.

The Activity Feed is a *cross-source event stream* — it doesn't own a
mart of its own; it merges three pre-existing event tables into one
severity-ranked timeline:

  * ``ingest_log``   — Excel → mart ingest runs (ok / partial / error).
  * ``usage_events`` — every Claude API call (agent slug + token cost).
  * ``llm_insights`` — cached Phase-6 recommendation payloads.

The page tagline is "Agent events and user actions, severity-ranked."
**User actions are deliberately deferred**: ``users.last_login`` stores
only the most recent login per user, not a history, so there's no
event stream to surface. A future commit can introduce a proper
``user_actions`` table; the schema here leaves room for it via the
generic ``actor`` / ``entity_ref`` fields.

Two response surfaces:

  * ``ActivityFeed``    — paginated list of normalized events.
  * ``ActivitySummary`` — counts by severity / kind / time window for
    the KPI tile strip at the top of the page.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums                                                                       #
# --------------------------------------------------------------------------- #


class ActivityKind(str, Enum):
    """What produced an activity row.

    The ``ingest_*`` triplet maps 1:1 to ``ingest_log.status`` so the
    UI can color-code on kind alone without having to read severity.
    """

    INGEST_OK = "ingest_ok"
    INGEST_PARTIAL = "ingest_partial"
    INGEST_FAILED = "ingest_failed"
    AGENT_CALL = "agent_call"
    INSIGHT_GENERATED = "insight_generated"


class ActivitySeverity(str, Enum):
    """How loud an event is in the UI.

    The severity ladder is independent of ``kind``: a normal agent
    call is ``info`` but a costly one (over the cost threshold) is
    ``warning``; a partial ingest is ``warning`` but a failed ingest
    is ``critical``.
    """

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


# --------------------------------------------------------------------------- #
# Feed                                                                        #
# --------------------------------------------------------------------------- #


class ActivityEvent(BaseModel):
    """One normalized row in the merged feed.

    ``id`` is composed as ``"{source}:{row_id}"`` so consumers can
    deep-link without worrying about UUID collisions across the three
    source tables. The frontend treats it as opaque.
    """

    id: str = Field(
        ...,
        description=(
            "Composite key: ``ingest:<uuid>`` / ``usage:<uuid>`` / "
            "``insight:<uuid>``. Stable across reloads; opaque to UI."
        ),
    )
    kind: ActivityKind
    severity: ActivitySeverity
    occurred_at: datetime = Field(
        ...,
        description=(
            "Source timestamp normalized to UTC. ``ingest_log`` uses "
            "``finished_at`` when available else ``started_at``."
        ),
    )
    actor: str | None = Field(
        None,
        description=(
            "Who/what produced the event. Agent slug for ``agent_call`` "
            "and ``insight_generated``; null for ``ingest_*`` rows "
            "(those are framework-driven, not user-driven)."
        ),
    )
    entity_ref: str | None = Field(
        None,
        description=(
            "Free-form entity hint for the UI: job number, mart name, "
            "module slug, etc. May be null."
        ),
    )
    summary: str = Field(
        ...,
        description=(
            "One-line human-readable description, e.g. "
            "'Ingested 2,008 rows into mart_productivity_labor' or "
            "'job_cost_coding agent — 1,243 in / 412 out tokens "
            "($0.012)'."
        ),
    )
    detail: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Source-specific extras the UI may surface in a popover: "
            "row counts, token counts, cost, target table, etc. "
            "Schema varies by ``kind`` — treat as opaque on read."
        ),
    )


class ActivityFeed(BaseModel):
    """Paginated, severity-ranked merge of the three source streams."""

    as_of: datetime
    items: list[ActivityEvent] = Field(
        ...,
        description=(
            "Ordered by (severity desc, occurred_at desc). Capped at "
            "``top_n``. The total before capping is reported in "
            "``total_matching`` so the UI can show 'showing N of M'."
        ),
    )
    total_returned: int = Field(
        ..., description="Length of ``items``.",
    )
    total_matching: int = Field(
        ...,
        description=(
            "How many events matched the filters before ``top_n`` was "
            "applied. ``total_matching >= total_returned`` always."
        ),
    )


# --------------------------------------------------------------------------- #
# Summary                                                                     #
# --------------------------------------------------------------------------- #


class ActivityCounts(BaseModel):
    """Bucket counts used by both severity and kind rollups."""

    critical: int = 0
    warning: int = 0
    info: int = 0


class ActivityKindCounts(BaseModel):
    """Per-kind counts. One field per ``ActivityKind`` enum value."""

    ingest_ok: int = 0
    ingest_partial: int = 0
    ingest_failed: int = 0
    agent_call: int = 0
    insight_generated: int = 0


class ActivitySummary(BaseModel):
    """Tile-strip rollup at the top of the Activity Feed page.

    Windows are computed against the same lookback the ``/events``
    endpoint uses by default, so the tiles and the feed always agree
    on what's "recent."
    """

    as_of: datetime
    last_24h: int = Field(
        ..., description="Events in the trailing 24 hours.",
    )
    last_7d: int = Field(
        ..., description="Events in the trailing 7 days.",
    )
    total: int = Field(
        ..., description="Events within the full lookback window.",
    )
    by_severity: ActivityCounts
    by_kind: ActivityKindCounts
