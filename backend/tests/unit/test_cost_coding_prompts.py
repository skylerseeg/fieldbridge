"""Prompt contract tests for cost-coding LLM recommendations."""
from __future__ import annotations

from app.modules.cost_coding.prompts import SYSTEM_PROMPT


def test_cost_coding_prompt_is_not_stub():
    assert "[STUB]" not in SYSTEM_PROMPT
    assert "submit_recommendations" in SYSTEM_PROMPT
    assert "app.core.llm" in SYSTEM_PROMPT


def test_cost_coding_prompt_documents_required_sections():
    assert "Quality bar:" in SYSTEM_PROMPT
    assert "Context shape" in SYSTEM_PROMPT
    assert "Style" in SYSTEM_PROMPT


def test_cost_coding_prompt_documents_context_keys():
    for key in (
        "summary",
        "category_breakdown",
        "size_tier_breakdown",
        "usage_tier_breakdown",
        "category_mix",
        "top_by_cost",
        "top_by_usage",
        "top_by_hours",
        "top_major_codes",
        "uncosted_codes",
    ):
        assert f"`{key}`" in SYSTEM_PROMPT


def test_cost_coding_prompt_documents_severity_rubric():
    assert "`critical`" in SYSTEM_PROMPT
    assert "uncosted / uncoded hygiene gaps" in SYSTEM_PROMPT
    assert "`warning`" in SYSTEM_PROMPT
    assert "code drift" in SYSTEM_PROMPT
    assert "`info`" in SYSTEM_PROMPT
    assert "cleanup batches" in SYSTEM_PROMPT
