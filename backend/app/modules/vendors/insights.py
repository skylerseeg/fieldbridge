"""Vendors Phase-6 insight pipeline.

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
from app.modules.vendors import service
from app.modules.vendors.prompts import SYSTEM_PROMPT

log = logging.getLogger("fieldbridge.vendors.insights")

MODULE_SLUG = "vendors"


def _build_data_context(engine: Engine, tenant_id: str) -> dict[str, Any]:
    """Compact directory-snapshot context for the LLM.

    Mirrors the JSON keys documented in
    :data:`app.modules.vendors.prompts.SYSTEM_PROMPT`.
    """
    summary = service.get_summary(engine, tenant_id)
    insights = service.get_insights(engine, tenant_id)

    summary_json = summary.model_dump(mode="json")
    insights_json = insights.model_dump(mode="json")

    return {
        "summary": summary_json,
        "firm_type_breakdown": insights_json.get("firm_type_breakdown", {}),
        "contact_health": insights_json.get("contact_health", {}),
        "coding_breakdown": insights_json.get("coding_breakdown", {}),
        "top_codes": insights_json.get("top_codes", []),
        "top_divisions": insights_json.get("top_divisions", []),
        "thin_divisions": insights_json.get("thin_divisions", []),
        "depth_leaders": insights_json.get("depth_leaders", []),
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
        log.warning("dropping unparseable cache row for vendors: %s", exc)
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
        log.warning("vendors insight cache write failed: %s", exc)


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
