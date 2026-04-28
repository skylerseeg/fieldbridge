"""Phase-6 LLM insight layer.

Single entry point — :func:`generate_insight` — wraps the Anthropic
Messages API with structured tool-use output. Every Phase-6
``GET /api/<module>/recommendations`` endpoint funnels through here so
the system prompt + tool schema + caching + error handling live in
exactly one place.

The function is deliberately stateless and DB-free. Cache reads/writes
live in :mod:`app.modules.<module>.insights` so the LLM helper can be
unit-tested without spinning up a SQLite engine.

Design notes
============

* **Model**: :data:`LLM_MODEL` defaults to ``"claude-opus-4-7"`` —
  the highest-leverage decision in this layer. Opus is reserved for
  the *moat* prompts (insight synthesis, recommendation ranking);
  Sonnet remains the workhorse for high-volume agents like coding
  and parsing. Update :data:`LLM_MODEL` here, not at every call site.

* **Structured output**: Claude is forced into a single
  ``submit_recommendations`` tool whose schema matches
  :class:`InsightResponse`. The pydantic ``model_validate`` call after
  the API response is the only place we accept LLM JSON — anything
  malformed raises and bubbles up to the route handler as a 502.

* **Prompt caching**: the system prompt is wrapped in an
  ``ephemeral`` cache_control block so repeated module calls within
  the 5-minute window pay the cache-read price (≈10×) instead of the
  full input price. The data context block is *not* cached because it
  changes on every call.

* **Offline / unset key**: if ``settings.anthropic_api_key`` is empty
  the function returns a stub :class:`InsightResponse` with one
  ``Severity.INFO`` row explaining the gap. That keeps the dev path
  working without a live key and keeps CI green; production callers
  must set the key.

* **Metering**: token usage is recorded into ``usage_events`` via
  :func:`app.services.metering.record_usage` when a tenant_id is
  passed in. Failures are logged but never surface to callers — a
  metering hiccup must not break the user-facing endpoint.

Schema
------

The :class:`Recommendation` model is the contract every module's
prompt template must satisfy. Adding fields here without updating
both the tool schema *and* every module's system prompt will silently
truncate output — keep them in lockstep.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings

log = logging.getLogger("fieldbridge.llm")


# --------------------------------------------------------------------------- #
# Constants                                                                   #
# --------------------------------------------------------------------------- #

#: Anthropic model identifier. Opus is reserved for the Phase-6 insight
#: layer; sonnet remains the default elsewhere. Override per-call via the
#: ``model`` arg to :func:`generate_insight` if a module needs to fall
#: back to sonnet for cost reasons.
LLM_MODEL = "claude-opus-4-7"

#: Hard ceiling on the data-context payload. Anthropic counts roughly
#: 4 chars per token; we budget for ~4k tokens of context, leaving the
#: bulk of the 200k-token window for the system prompt + output. Module
#: insights services trim before calling :func:`generate_insight`.
MAX_CONTEXT_CHARS = 16_000

#: Hard ceiling on output tokens — recommendations are short prose
#: bullets, never essays.
MAX_OUTPUT_TOKENS = 2_000


# --------------------------------------------------------------------------- #
# Pydantic schema (the moat contract)                                         #
# --------------------------------------------------------------------------- #


class Severity(str, Enum):
    """How urgent the recommendation is.

    The frontend right rail color-codes by severity:
      * ``critical`` — red, demands action this week.
      * ``warning``  — amber, demands action this month.
      * ``info``     — blue, opportunity rather than blocker.
    """

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class Recommendation(BaseModel):
    """One ranked next-action emitted by Claude.

    Keep field names and order matching the tool schema in
    :func:`_recommendation_tool` — the LLM emits these as JSON keys,
    so a rename here without a matching update there breaks parsing.
    """

    title: str = Field(
        ...,
        min_length=4,
        max_length=120,
        description="Imperative one-liner. Starts with a verb.",
    )
    severity: Severity = Field(
        ...,
        description="critical / warning / info — drives the right-rail tone.",
    )
    rationale: str = Field(
        ...,
        min_length=10,
        max_length=600,
        description=(
            "1–3 sentences explaining *why* this recommendation surfaced — "
            "must cite specific numbers from the data context."
        ),
    )
    suggested_action: str = Field(
        ...,
        min_length=4,
        max_length=400,
        description=(
            "Concrete next step the user can take. Names a role, asset, "
            "or vendor where possible."
        ),
    )
    affected_assets: list[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Stable IDs (truck names, vendor IDs, job numbers, …) the "
            "recommendation applies to. Empty list when fleet-wide."
        ),
    )


class InsightResponse(BaseModel):
    """Top-level payload returned by :func:`generate_insight` and
    cached in ``llm_insights.payload_json``."""

    module: str = Field(
        ...,
        description="Slug of the module that produced this payload.",
    )
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp the LLM call completed.",
    )
    model: str = Field(
        default=LLM_MODEL,
        description="Claude model identifier used for this generation.",
    )
    revision_token: str = Field(
        ...,
        description=(
            "SHA-256 (first 16 bytes) of the data context — the cache "
            "stale-detection key."
        ),
    )
    recommendations: list[Recommendation] = Field(default_factory=list)

    # Token telemetry. Optional — the offline-stub path leaves these
    # at zero. Real LLM calls populate them off ``response.usage``.
    input_tokens: int = 0
    output_tokens: int = 0

    #: Set when the response is the offline stub (no API key, or the
    #: API call raised). Frontend renders a "configure key" hint.
    is_stub: bool = False


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def hash_data_context(data_context: dict[str, Any]) -> str:
    """Deterministic 16-byte SHA-256 prefix of the JSON-serialized context.

    Used as the cache stale-detection key. Sort keys so dict order
    doesn't churn the hash; coerce datetimes/Enums/etc. via str().
    """
    raw = json.dumps(data_context, sort_keys=True, default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return digest[:16]


def _format_context(data_context: dict[str, Any]) -> str:
    """Render the data context as a compact, human-readable block.

    We use sorted JSON over more aggressive trimming because Claude
    handles structured input cleanly, and structured input keeps the
    LLM's citations honest (it can quote the field names back).
    """
    raw = json.dumps(data_context, indent=2, sort_keys=True, default=str)
    if len(raw) > MAX_CONTEXT_CHARS:
        # Aggressive trim — module insights services should pre-shape
        # this. If we get here something upstream is wrong; log loudly.
        log.warning(
            "data_context exceeds %d chars (got %d), truncating",
            MAX_CONTEXT_CHARS,
            len(raw),
        )
        raw = raw[:MAX_CONTEXT_CHARS] + "\n…[truncated]"
    return raw


def _recommendation_tool() -> dict[str, Any]:
    """Tool-use schema that mirrors :class:`InsightResponse`.

    Anthropic supports JSON Schema in the ``input_schema`` field. We
    keep this hand-written rather than auto-generated from pydantic
    so the description strings can be tuned for the LLM (which reads
    them as part of the prompt) independently from the python field
    descriptions (which serve API consumers).
    """
    return {
        "name": "submit_recommendations",
        "description": (
            "Return a ranked list of actionable recommendations for the "
            "current FieldBridge module. Each recommendation must cite "
            "specific numbers from the data context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "recommendations": {
                    "type": "array",
                    "minItems": 0,
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": (
                                    "Imperative one-liner under 120 chars. "
                                    "Starts with a verb."
                                ),
                            },
                            "severity": {
                                "type": "string",
                                "enum": ["critical", "warning", "info"],
                                "description": (
                                    "How urgent. Reserve `critical` for "
                                    "outliers > 2σ from the cohort or "
                                    "explicit safety/cash gaps."
                                ),
                            },
                            "rationale": {
                                "type": "string",
                                "description": (
                                    "1–3 sentences quoting specific "
                                    "numbers from the data context."
                                ),
                            },
                            "suggested_action": {
                                "type": "string",
                                "description": (
                                    "Concrete next step naming a role, "
                                    "asset, or vendor where possible."
                                ),
                            },
                            "affected_assets": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "Stable IDs the recommendation "
                                    "applies to. Empty when fleet-wide."
                                ),
                            },
                        },
                        "required": [
                            "title",
                            "severity",
                            "rationale",
                            "suggested_action",
                        ],
                    },
                },
            },
            "required": ["recommendations"],
        },
    }


def _stub_response(module: str, revision_token: str, reason: str) -> InsightResponse:
    """Offline stub used when no API key is configured or the call fails."""
    return InsightResponse(
        module=module,
        revision_token=revision_token,
        is_stub=True,
        recommendations=[
            Recommendation(
                title=f"Configure ANTHROPIC_API_KEY to enable {module} insights",
                severity=Severity.INFO,
                rationale=(
                    f"The Phase-6 insight layer is not generating live "
                    f"recommendations for the {module} module. Reason: "
                    f"{reason}"
                ),
                suggested_action=(
                    "Set ANTHROPIC_API_KEY in the backend .env, restart "
                    "the API, then refresh this panel."
                ),
                affected_assets=[],
            ),
        ],
    )


# --------------------------------------------------------------------------- #
# Anthropic client (lazy)                                                     #
# --------------------------------------------------------------------------- #


_client = None


def _get_client():
    """Lazy-construct the Anthropic SDK client.

    Lazy so importing this module never raises if the SDK is missing
    in some deployments (e.g. CI-only test runs that monkeypatch
    :func:`generate_insight` away).
    """
    global _client
    if _client is None:
        import anthropic  # local import — only required when actually calling

        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


# --------------------------------------------------------------------------- #
# Public entry point                                                          #
# --------------------------------------------------------------------------- #


def generate_insight(
    module: str,
    data_context: dict[str, Any],
    prompt_template: str,
    *,
    tenant_id: str | None = None,
    model: str = LLM_MODEL,
    max_output_tokens: int = MAX_OUTPUT_TOKENS,
) -> InsightResponse:
    """Generate a structured :class:`InsightResponse` for ``module``.

    Parameters
    ----------
    module
        Slug of the calling module — copied into the response and used
        as the metering ``agent`` key.
    data_context
        JSON-serializable dict describing the last-30-days slice the
        module wants the LLM to reason over. Service callers should
        cap this at ≈4k tokens before passing in.
    prompt_template
        Module-specific system prompt body. Lives in
        ``app.modules.<module>.prompts.SYSTEM_PROMPT``.
    tenant_id
        When provided, token usage is logged to ``usage_events``. When
        absent (e.g. one-off scripts), metering is skipped.
    model
        Override the default Opus-4 model. Rare — most callers should
        accept the default.
    max_output_tokens
        Hard ceiling on the LLM response.

    Returns
    -------
    InsightResponse
        Pydantic-validated. Even on failure paths a valid response is
        returned (with ``is_stub=True``); callers never have to catch.
    """
    revision_token = hash_data_context(data_context)

    if not settings.anthropic_api_key:
        log.info("anthropic_api_key not set — returning stub for %s", module)
        return _stub_response(
            module, revision_token, "ANTHROPIC_API_KEY is not configured.",
        )

    try:
        client = _get_client()
    except Exception as exc:  # noqa: BLE001 — we want every failure to stub
        log.warning("anthropic SDK unavailable: %s", exc)
        return _stub_response(module, revision_token, f"SDK error: {exc}")

    formatted_context = _format_context(data_context)
    user_message = (
        "Here is the last-30-days data context for the "
        f"{module} module. Read it carefully, then call the "
        "`submit_recommendations` tool with your ranked list.\n\n"
        f"```json\n{formatted_context}\n```"
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_output_tokens,
            system=[
                {
                    "type": "text",
                    "text": prompt_template,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            tools=[_recommendation_tool()],
            tool_choice={"type": "tool", "name": "submit_recommendations"},
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as exc:  # noqa: BLE001 — same rationale as above
        log.warning("Claude call failed for %s: %s", module, exc)
        return _stub_response(module, revision_token, f"API error: {exc}")

    # Extract the single tool_use block.
    tool_block = next(
        (b for b in response.content if getattr(b, "type", None) == "tool_use"),
        None,
    )
    if tool_block is None:
        log.warning(
            "Claude did not invoke submit_recommendations for %s — "
            "got blocks: %s",
            module,
            [getattr(b, "type", "?") for b in response.content],
        )
        return _stub_response(
            module, revision_token, "Claude did not produce a tool_use block.",
        )

    try:
        recs = [Recommendation.model_validate(r) for r in tool_block.input["recommendations"]]
    except (KeyError, ValidationError) as exc:
        log.warning("Claude output failed validation for %s: %s", module, exc)
        return _stub_response(
            module, revision_token, f"Validation error: {exc}",
        )

    usage = getattr(response, "usage", None)
    in_tok = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    out_tok = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
    cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0) if usage else 0
    cache_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0) if usage else 0

    if tenant_id is not None:
        _meter_async(
            tenant_id=tenant_id,
            module=module,
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )

    return InsightResponse(
        module=module,
        model=model,
        revision_token=revision_token,
        recommendations=recs,
        input_tokens=in_tok,
        output_tokens=out_tok,
        is_stub=False,
    )


def _meter_async(
    *,
    tenant_id: str,
    module: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
) -> None:
    """Best-effort token-usage logging.

    The metering helper is async because it writes through the async
    SQLAlchemy session. We're called from sync FastAPI route handlers
    here, so we hop through ``asyncio.run`` (or ``ensure_future`` when
    a loop is already running). Failures are swallowed — metering must
    not break the user-facing endpoint.
    """
    try:
        from app.core.database import AsyncSessionLocal
        from app.services.metering import record_usage

        async def _do():
            async with AsyncSessionLocal() as session:
                await record_usage(
                    session,
                    tenant_id=tenant_id,
                    agent=f"insights:{module}",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_write_tokens=cache_write_tokens,
                    model=model,
                )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is None:
            asyncio.run(_do())
        else:
            loop.create_task(_do())
    except Exception as exc:  # noqa: BLE001
        log.debug("metering skipped for insights:%s — %s", module, exc)
