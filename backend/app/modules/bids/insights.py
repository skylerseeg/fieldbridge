"""Bids Phase-6 insight pipeline.

Glue between ``service.get_summary`` / ``service.get_insights`` and
``app.core.llm.generate_insight``, with the same cache rules as the
equipment pipeline. See :mod:`app.modules.equipment.insights` for the
canonical doc — this module is a structural mirror.
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
from app.modules.bids import service
from app.modules.bids.prompts import SYSTEM_PROMPT

log = logging.getLogger("fieldbridge.bids.insights")

MODULE_SLUG = "bids"


def _build_data_context(engine: Engine, tenant_id: str) -> dict[str, Any]:
    """Compact bid-strategy context for the LLM.

    Mirrors the JSON keys documented in
    :data:`app.modules.bids.prompts.SYSTEM_PROMPT`.
    """
    summary = service.get_summary(engine, tenant_id)
    insights = service.get_insights(engine, tenant_id, top_n=20)

    summary_json = summary.model_dump(mode="json")
    insights_json = insights.model_dump(mode="json")

    return {
        "summary": summary_json,
        "close_max": service.DEFAULT_CLOSE_MARGIN_MAX,
        "moderate_max": service.DEFAULT_MODERATE_MARGIN_MAX,
        "light_max": service.DEFAULT_LIGHT_BIDDERS_MAX,
        "typical_max": service.DEFAULT_TYPICAL_BIDDERS_MAX,
        "outcome_breakdown": insights_json.get("outcome_breakdown", {}),
        "margin_tier_breakdown": insights_json.get("margin_tier_breakdown", {}),
        "competition_tier_breakdown": insights_json.get(
            "competition_tier_breakdown", {},
        ),
        "win_rate_by_bid_type": insights_json.get("win_rate_by_bid_type", []),
        "win_rate_by_estimator": insights_json.get("win_rate_by_estimator", []),
        "win_rate_by_county": insights_json.get("win_rate_by_county", []),
        "near_misses": insights_json.get("near_misses", []),
        "big_wins": insights_json.get("big_wins", []),
        "risk_flag_frequency": insights_json.get("risk_flag_frequency", []),
    }


def _load_cached(
    engine: Engine, tenant_id: str, revision_token: str,
) -> InsightResponse | None:
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
    except Exception as exc:  # noqa: BLE001
        log.warning("dropping unparseable cache row for bids: %s", exc)
        return None


def _upsert_cache(
    engine: Engine,
    tenant_id: str,
    response: InsightResponse,
) -> None:
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
        log.warning("bids insight cache write failed: %s", exc)


def build_recommendations(
    engine: Engine,
    tenant_id: str,
    *,
    force_refresh: bool = False,
) -> InsightResponse:
    """Public entry point used by the ``/recommendations`` endpoint."""
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
