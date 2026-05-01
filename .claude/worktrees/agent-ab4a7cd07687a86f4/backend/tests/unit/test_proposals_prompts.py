"""Prompt contract tests for proposals LLM recommendations."""
from __future__ import annotations

from app.modules.proposals.prompts import SYSTEM_PROMPT


def test_proposals_prompt_is_not_stub():
    assert "[STUB]" not in SYSTEM_PROMPT
    assert "submit_recommendations" in SYSTEM_PROMPT
    assert "app.core.llm" in SYSTEM_PROMPT


def test_proposals_prompt_documents_required_sections():
    assert "Quality bar:" in SYSTEM_PROMPT
    assert "Context shape" in SYSTEM_PROMPT
    assert "Style" in SYSTEM_PROMPT


def test_proposals_prompt_documents_context_keys():
    for key in (
        "summary",
        "primary_state",
        "bid_type_category_breakdown",
        "geography_tier_breakdown",
        "top_owners",
        "top_bid_types",
        "top_counties",
        "top_states",
        "competitor_frequency",
        "fee_statistics",
    ):
        assert f"`{key}`" in SYSTEM_PROMPT


def test_proposals_prompt_documents_severity_rubric():
    assert "`critical`" in SYSTEM_PROMPT
    assert "competitor pricing pattern shifts" in SYSTEM_PROMPT
    assert "`warning`" in SYSTEM_PROMPT
    assert "geography over-extension" in SYSTEM_PROMPT
    assert "`info`" in SYSTEM_PROMPT
    assert "bid-type performance" in SYSTEM_PROMPT
