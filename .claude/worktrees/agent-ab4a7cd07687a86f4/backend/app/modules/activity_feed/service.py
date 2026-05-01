"""Activity Feed service — pure cross-source event normalization.

Reads three pre-existing event tables and merges them into one
severity-ranked timeline:

  * ``ingest_log``   — Excel → mart ingest runs
  * ``usage_events`` — Claude API calls (per agent + cost)
  * ``llm_insights`` — cached Phase-6 recommendation payloads

No mart of its own; no writes. The page tagline is "Agent events and
user actions, severity-ranked." User actions are deliberately deferred
because ``users.last_login`` only stores the most recent login per
user, not a history — see schema.py module docstring.

Severity rules (all derived, never persisted):

  * ``ingest_log.status="error"``   -> critical / kind=ingest_failed
  * ``ingest_log.status="partial"`` -> warning  / kind=ingest_partial
  * ``ingest_log.status="ok"``      -> info     / kind=ingest_ok
  * ``usage_events.cost_usd >= AGENT_CALL_COST_THRESHOLD``
                                    -> warning  / kind=agent_call
  * any other ``usage_events`` row  -> info     / kind=agent_call
  * any ``llm_insights`` row        -> info     / kind=insight_generated

Functions take ``Engine`` + ``tenant_id`` so tests inject a fixture
engine. No ORM mappers — raw ``text()`` against the source tables.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import Engine, text

from app.modules.activity_feed.schema import (
    ActivityCounts,
    ActivityEvent,
    ActivityFeed,
    ActivityKind,
    ActivityKindCounts,
    ActivitySeverity,
    ActivitySummary,
)


log = logging.getLogger("fieldbridge.activity_feed")


# --------------------------------------------------------------------------- #
# Tunables                                                                    #
# --------------------------------------------------------------------------- #

# Default page size for ``GET /events``. Frontend tile-strip + feed
# fits comfortably under 50 rows; raise the cap, not the default, if a
# power-user view ever needs more.
DEFAULT_TOP_N = 50
MAX_TOP_N = 250

# How far back the feed and summary look by default. 30 days lines up
# with the executive dashboard's trailing window so the two pages tell
# the same story when opened side-by-side.
DEFAULT_LOOKBACK_DAYS = 30
MAX_LOOKBACK_DAYS = 365

# A single Claude call costing more than this is loud enough to
# surface as a warning even though the kind is just ``agent_call``.
# Tuned to flag full-context Phase-6 insight regenerations (~$0.05–
# $0.20 typical) only when something is genuinely off — runaway
# retries, agents stuck in loops, etc.
AGENT_CALL_COST_THRESHOLD = 0.50


# Severity sort key. Higher number = louder.
_SEVERITY_RANK: dict[ActivitySeverity, int] = {
    ActivitySeverity.CRITICAL: 3,
    ActivitySeverity.WARNING: 2,
    ActivitySeverity.INFO: 1,
}


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _normalize_dt(v: Any) -> datetime | None:
    """SQLite stores DateTime as ISO strings; coerce back to datetime.

    Mirrors the helper used in executive_dashboard.service for
    consistency across modules.
    """
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None


def _ensure_aware(dt: datetime) -> datetime:
    """Tag naive datetimes as UTC so downstream comparisons don't blow up."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_since(
    *, since: datetime | None, lookback_days: int | None,
) -> datetime:
    """Pick the effective lower bound for event filtering.

    ``since`` (if passed) wins; otherwise ``now - lookback_days``.
    Falls back to ``DEFAULT_LOOKBACK_DAYS`` when both are None.
    """
    if since is not None:
        return _ensure_aware(since)
    days = lookback_days if lookback_days is not None else DEFAULT_LOOKBACK_DAYS
    days = max(1, min(days, MAX_LOOKBACK_DAYS))
    return _now() - timedelta(days=days)


def _fmt_int(n: Any) -> str:
    """Thousand-separated int for human-readable summaries."""
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "0"


def _coalesce_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


# --------------------------------------------------------------------------- #
# Severity classifiers                                                         #
# --------------------------------------------------------------------------- #


def _ingest_classify(status: str) -> tuple[ActivityKind, ActivitySeverity]:
    """Map ``ingest_log.status`` to (kind, severity)."""
    s = (status or "").strip().lower()
    if s == "error":
        return ActivityKind.INGEST_FAILED, ActivitySeverity.CRITICAL
    if s == "partial":
        return ActivityKind.INGEST_PARTIAL, ActivitySeverity.WARNING
    # Treat anything else (including "ok") as a clean run.
    return ActivityKind.INGEST_OK, ActivitySeverity.INFO


def _agent_call_severity(cost_usd: float | None) -> ActivitySeverity:
    if cost_usd is not None and cost_usd >= AGENT_CALL_COST_THRESHOLD:
        return ActivitySeverity.WARNING
    return ActivitySeverity.INFO


# --------------------------------------------------------------------------- #
# Source-fetch helpers                                                         #
# --------------------------------------------------------------------------- #


def _fetch_ingest_events(
    engine: Engine, tenant_id: str, since: datetime,
) -> list[ActivityEvent]:
    """Pull ingest_log rows since ``since`` and normalize them."""
    sql = text(
        """
        SELECT id,
               job_name,
               source_file,
               target_table,
               status,
               rows_read,
               rows_written,
               rows_skipped,
               errors,
               duration_ms,
               started_at,
               finished_at
          FROM ingest_log
         WHERE tenant_id = :tenant_id
           AND started_at >= :since
        """
    )
    out: list[ActivityEvent] = []
    with engine.connect() as conn:
        rows = conn.execute(sql, {"tenant_id": tenant_id, "since": since}).mappings()
        for r in rows:
            kind, severity = _ingest_classify(r["status"])
            finished = _normalize_dt(r["finished_at"])
            started = _normalize_dt(r["started_at"])
            occurred = _ensure_aware(finished or started or _now())

            target = _coalesce_str(r["target_table"], "(unknown table)")
            rows_written = int(r["rows_written"] or 0)
            rows_read = int(r["rows_read"] or 0)
            rows_skipped = int(r["rows_skipped"] or 0)

            if kind is ActivityKind.INGEST_OK:
                summary = (
                    f"Ingested {_fmt_int(rows_written)} rows into {target}"
                )
            elif kind is ActivityKind.INGEST_PARTIAL:
                summary = (
                    f"Partial ingest of {target}: "
                    f"{_fmt_int(rows_written)} written, "
                    f"{_fmt_int(rows_skipped)} skipped"
                )
            else:  # INGEST_FAILED
                summary = f"Ingest failed for {target}"

            # Keep the errors blob bounded — the UI popover doesn't
            # need the full backtrace.
            errors_raw = r["errors"] or ""
            errors_list: list[str] = []
            if errors_raw:
                try:
                    parsed = json.loads(errors_raw)
                    if isinstance(parsed, list):
                        errors_list = [str(x) for x in parsed[:10]]
                    else:
                        errors_list = [str(parsed)[:500]]
                except (TypeError, ValueError):
                    errors_list = [str(errors_raw)[:500]]

            detail: dict[str, Any] = {
                "job_name": _coalesce_str(r["job_name"]),
                "source_file": _coalesce_str(r["source_file"]),
                "target_table": target,
                "status": _coalesce_str(r["status"]),
                "rows_read": rows_read,
                "rows_written": rows_written,
                "rows_skipped": rows_skipped,
                "duration_ms": int(r["duration_ms"] or 0),
            }
            if errors_list:
                detail["errors"] = errors_list

            out.append(
                ActivityEvent(
                    id=f"ingest:{r['id']}",
                    kind=kind,
                    severity=severity,
                    occurred_at=occurred,
                    actor=None,
                    entity_ref=_coalesce_str(r["job_name"]) or target,
                    summary=summary,
                    detail=detail,
                )
            )
    return out


def _fetch_agent_calls(
    engine: Engine, tenant_id: str, since: datetime,
) -> list[ActivityEvent]:
    """Pull usage_events rows since ``since`` and normalize them."""
    sql = text(
        """
        SELECT id,
               agent,
               model,
               input_tokens,
               output_tokens,
               cache_read_tokens,
               cache_write_tokens,
               cost_usd,
               job_number,
               equipment_id,
               user_id,
               created_at
          FROM usage_events
         WHERE tenant_id = :tenant_id
           AND created_at >= :since
        """
    )
    out: list[ActivityEvent] = []
    with engine.connect() as conn:
        rows = conn.execute(sql, {"tenant_id": tenant_id, "since": since}).mappings()
        for r in rows:
            cost = float(r["cost_usd"] or 0.0)
            severity = _agent_call_severity(cost)
            created = _normalize_dt(r["created_at"])
            occurred = _ensure_aware(created or _now())

            agent_slug = _coalesce_str(r["agent"], "(unknown agent)")
            in_tok = int(r["input_tokens"] or 0)
            out_tok = int(r["output_tokens"] or 0)

            # The summary string mirrors the Activity Feed mock:
            # "<agent> agent — 1,243 in / 412 out tokens ($0.012)".
            summary = (
                f"{agent_slug} agent — "
                f"{_fmt_int(in_tok)} in / {_fmt_int(out_tok)} out tokens "
                f"(${cost:,.4f})"
            )

            entity_ref = (
                _coalesce_str(r["job_number"])
                or _coalesce_str(r["equipment_id"])
                or None
            )

            detail: dict[str, Any] = {
                "agent": agent_slug,
                "model": _coalesce_str(r["model"]),
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "cache_read_tokens": int(r["cache_read_tokens"] or 0),
                "cache_write_tokens": int(r["cache_write_tokens"] or 0),
                "cost_usd": cost,
            }
            job_number = _coalesce_str(r["job_number"])
            equipment_id = _coalesce_str(r["equipment_id"])
            user_id = _coalesce_str(r["user_id"])
            if job_number:
                detail["job_number"] = job_number
            if equipment_id:
                detail["equipment_id"] = equipment_id
            if user_id:
                detail["user_id"] = user_id

            out.append(
                ActivityEvent(
                    id=f"usage:{r['id']}",
                    kind=ActivityKind.AGENT_CALL,
                    severity=severity,
                    occurred_at=occurred,
                    actor=agent_slug,
                    entity_ref=entity_ref,
                    summary=summary,
                    detail=detail,
                )
            )
    return out


def _fetch_insight_events(
    engine: Engine, tenant_id: str, since: datetime,
) -> list[ActivityEvent]:
    """Pull llm_insights rows since ``since`` and normalize them."""
    sql = text(
        """
        SELECT id,
               module,
               revision_token,
               input_tokens,
               output_tokens,
               model,
               created_at,
               expires_at
          FROM llm_insights
         WHERE tenant_id = :tenant_id
           AND created_at >= :since
        """
    )
    out: list[ActivityEvent] = []
    with engine.connect() as conn:
        rows = conn.execute(sql, {"tenant_id": tenant_id, "since": since}).mappings()
        for r in rows:
            created = _normalize_dt(r["created_at"])
            expires = _normalize_dt(r["expires_at"])
            occurred = _ensure_aware(created or _now())
            module_slug = _coalesce_str(r["module"], "(unknown)")

            in_tok = int(r["input_tokens"] or 0)
            out_tok = int(r["output_tokens"] or 0)

            summary = (
                f"Cached insight for {module_slug} module "
                f"({_fmt_int(in_tok)} in / {_fmt_int(out_tok)} out tokens)"
            )

            detail: dict[str, Any] = {
                "module": module_slug,
                "revision_token": _coalesce_str(r["revision_token"]),
                "model": _coalesce_str(r["model"]),
                "input_tokens": in_tok,
                "output_tokens": out_tok,
            }
            if expires is not None:
                detail["expires_at"] = _ensure_aware(expires).isoformat()

            out.append(
                ActivityEvent(
                    id=f"insight:{r['id']}",
                    kind=ActivityKind.INSIGHT_GENERATED,
                    severity=ActivitySeverity.INFO,
                    occurred_at=occurred,
                    # The "actor" of a cached insight is the module
                    # whose recommendations endpoint produced it.
                    actor=module_slug,
                    entity_ref=module_slug,
                    summary=summary,
                    detail=detail,
                )
            )
    return out


# --------------------------------------------------------------------------- #
# Sort + filter                                                                #
# --------------------------------------------------------------------------- #


def _sort_events(events: Iterable[ActivityEvent]) -> list[ActivityEvent]:
    """Sort by (severity desc, occurred_at desc).

    The UI shows the loudest, most recent things on top — within a
    severity tier, newer events outrank older ones.
    """
    return sorted(
        events,
        key=lambda e: (
            -_SEVERITY_RANK[e.severity],
            -_ensure_aware(e.occurred_at).timestamp(),
        ),
    )


def _apply_filters(
    events: Iterable[ActivityEvent],
    *,
    kind: ActivityKind | None,
    severity: ActivitySeverity | None,
) -> list[ActivityEvent]:
    out: list[ActivityEvent] = []
    for e in events:
        if kind is not None and e.kind is not kind:
            continue
        if severity is not None and e.severity is not severity:
            continue
        out.append(e)
    return out


def _gather_all(
    engine: Engine, tenant_id: str, since: datetime,
) -> list[ActivityEvent]:
    """Fan out across the three sources and concat the results."""
    events: list[ActivityEvent] = []
    events.extend(_fetch_ingest_events(engine, tenant_id, since))
    events.extend(_fetch_agent_calls(engine, tenant_id, since))
    events.extend(_fetch_insight_events(engine, tenant_id, since))
    return events


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #


def get_feed(
    engine: Engine,
    tenant_id: str,
    *,
    top_n: int = DEFAULT_TOP_N,
    since: datetime | None = None,
    lookback_days: int | None = None,
    kind: ActivityKind | None = None,
    severity: ActivitySeverity | None = None,
) -> ActivityFeed:
    """Merged, severity-ranked event timeline for one tenant.

    ``top_n`` caps the returned list; ``total_matching`` reports the
    pre-cap count so the UI can show "showing N of M".
    """
    top_n = max(1, min(top_n, MAX_TOP_N))
    effective_since = _resolve_since(since=since, lookback_days=lookback_days)

    raw = _gather_all(engine, tenant_id, effective_since)
    filtered = _apply_filters(raw, kind=kind, severity=severity)
    ordered = _sort_events(filtered)
    capped = ordered[:top_n]

    return ActivityFeed(
        as_of=_now(),
        items=capped,
        total_returned=len(capped),
        total_matching=len(ordered),
    )


def get_summary(
    engine: Engine,
    tenant_id: str,
    *,
    lookback_days: int | None = None,
) -> ActivitySummary:
    """Tile-strip rollup: counts by severity, kind, and time window.

    Lookback governs the ``total`` and the ``by_*`` rollups; ``last_24h``
    and ``last_7d`` are computed off the same gathered set so they
    always agree with the visible feed.
    """
    effective_since = _resolve_since(since=None, lookback_days=lookback_days)
    events = _gather_all(engine, tenant_id, effective_since)

    now = _now()
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)

    last_24h = 0
    last_7d = 0
    sev_counter: Counter[str] = Counter()
    kind_counter: Counter[str] = Counter()

    for e in events:
        occ = _ensure_aware(e.occurred_at)
        if occ >= cutoff_24h:
            last_24h += 1
        if occ >= cutoff_7d:
            last_7d += 1
        sev_counter[e.severity.value] += 1
        kind_counter[e.kind.value] += 1

    return ActivitySummary(
        as_of=now,
        last_24h=last_24h,
        last_7d=last_7d,
        total=len(events),
        by_severity=ActivityCounts(
            critical=sev_counter.get(ActivitySeverity.CRITICAL.value, 0),
            warning=sev_counter.get(ActivitySeverity.WARNING.value, 0),
            info=sev_counter.get(ActivitySeverity.INFO.value, 0),
        ),
        by_kind=ActivityKindCounts(
            ingest_ok=kind_counter.get(ActivityKind.INGEST_OK.value, 0),
            ingest_partial=kind_counter.get(ActivityKind.INGEST_PARTIAL.value, 0),
            ingest_failed=kind_counter.get(ActivityKind.INGEST_FAILED.value, 0),
            agent_call=kind_counter.get(ActivityKind.AGENT_CALL.value, 0),
            insight_generated=kind_counter.get(
                ActivityKind.INSIGHT_GENERATED.value, 0,
            ),
        ),
    )
