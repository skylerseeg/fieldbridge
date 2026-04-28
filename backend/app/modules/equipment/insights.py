"""Equipment Phase-6 insight pipeline.

Glue between the existing ``service.get_summary`` / ``service.get_insights``
mart queries and ``app.core.llm.generate_insight``. Maintains the
``llm_insights`` cache row keyed on ``(tenant_id, "equipment")``.

Cache rules
-----------

1. Look up the existing row. If it's both non-expired (≤6h old) AND
   the stored ``revision_token`` matches the current data-context
   hash, return the cached payload — no LLM call.
2. Otherwise call :func:`generate_insight` and upsert the row.
3. Stub responses (when ``ANTHROPIC_API_KEY`` is unset) are still
   cached — they're cheap to produce, but caching keeps the response
   shape and timestamps stable across reloads, which makes the
   frontend "configure key" hint less flickery.

The cache is best-effort: if the DB write fails we still return the
freshly generated payload. We never raise from this function — the
route handler should never have to surface a 5xx because the LLM
layer hiccupped.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from app.core.llm import (
    InsightResponse,
    generate_insight,
    hash_data_context,
)
from app.models.llm_insight import DEFAULT_TTL_HOURS, LlmInsight
from app.modules.equipment import service
from app.modules.equipment.prompts import SYSTEM_PROMPT

log = logging.getLogger("fieldbridge.equipment.insights")

MODULE_SLUG = "equipment"


def _build_data_context(engine: Engine, tenant_id: str) -> dict[str, Any]:
    """Compact 30-day slice the LLM reasons over.

    Mirrors the JSON keys documented in
    :data:`app.modules.equipment.prompts.SYSTEM_PROMPT`. Update both in
    lockstep — the prompt cites these field names directly.
    """
    summary = service.get_summary(engine, tenant_id)
    insights = service.get_insights(engine, tenant_id, top_n=20)

    # ``model_dump(mode="json")`` so datetimes/Enums become strings — the
    # LLM gets a clean JSON payload, and our hash is stable across runs.
    summary_json = summary.model_dump(mode="json")
    insights_json = insights.model_dump(mode="json")

    return {
        "summary": summary_json,
        "utilization_buckets": insights_json.get("utilization_buckets", {}),
        "fuel_cost_per_hour_by_asset": insights_json.get(
            "fuel_cost_per_hour_by_asset", [],
        ),
        "rental_vs_owned": insights_json.get("rental_vs_owned", {}),
    }


def _load_cached(
    engine: Engine, tenant_id: str, revision_token: str,
) -> InsightResponse | None:
    """Return the cached :class:`InsightResponse` if fresh, else ``None``."""
    SessionLocal = sessionmaker(engine)
    with SessionLocal() as s:
        row = s.execute(
            select(LlmInsight).where(
                LlmInsight.tenant_id == tenant_id,
                LlmInsight.module == MODULE_SLUG,
            )
        ).scalar_one_or_none()

    if row is None:
        return None
    if not row.is_fresh(revision_token):
        return None

    try:
        return InsightResponse.model_validate_json(row.payload_json)
    except Exception as exc:  # noqa: BLE001 — bad cache row, treat as miss
        log.warning("dropping unparseable cache row for equipment: %s", exc)
        return None


def _upsert_cache(
    engine: Engine,
    tenant_id: str,
    response: InsightResponse,
) -> None:
    """Write/refresh the cached row. Best-effort — swallows exceptions."""
    try:
        SessionLocal = sessionmaker(engine)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=DEFAULT_TTL_HOURS)
        with SessionLocal() as s:
            existing = s.execute(
                select(LlmInsight).where(
                    LlmInsight.tenant_id == tenant_id,
                    LlmInsight.module == MODULE_SLUG,
                )
            ).scalar_one_or_none()

            payload = response.model_dump_json()
            if existing is None:
                s.add(
                    LlmInsight(
                        tenant_id=tenant_id,
                        module=MODULE_SLUG,
                        revision_token=response.revision_token,
                        payload_json=payload,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        model=response.model,
                        created_at=now,
                        expires_at=expires_at,
                    )
                )
            else:
                existing.revision_token = response.revision_token
                existing.payload_json = payload
                existing.input_tokens = response.input_tokens
                existing.output_tokens = response.output_tokens
                existing.model = response.model
                existing.created_at = now
                existing.expires_at = expires_at
            s.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("equipment insight cache write failed: %s", exc)


def build_recommendations(
    engine: Engine,
    tenant_id: str,
    *,
    force_refresh: bool = False,
) -> InsightResponse:
    """Public entry point used by the ``/recommendations`` endpoint.

    Parameters
    ----------
    engine
        Sync SQLAlchemy engine pointed at the marts DB.
    tenant_id
        UUID of the tenant whose data we're analyzing.
    force_refresh
        Bypass the cache and force a fresh LLM call — used by the
        admin "regenerate" button (not yet wired).
    """
    data_context = _build_data_context(engine, tenant_id)
    revision_token = hash_data_context(data_context)

    if not force_refresh:
        cached = _load_cached(engine, tenant_id, revision_token)
        if cached is not None:
            return cached

    response = generate_insight(
        MODULE_SLUG,
        data_context,
        SYSTEM_PROMPT,
        tenant_id=tenant_id,
    )
    _upsert_cache(engine, tenant_id, response)
    return response
