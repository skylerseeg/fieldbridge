"""Prompt contract tests for bids LLM recommendations."""
from __future__ import annotations

from app.modules.bids.prompts import SYSTEM_PROMPT


def test_bids_prompt_is_not_stub():
    assert "[STUB]" not in SYSTEM_PROMPT
    assert "submit_recommendations" in SYSTEM_PROMPT
    assert "app.core.llm" in SYSTEM_PROMPT


def test_bids_prompt_documents_required_sections():
    assert "Quality bar:" in SYSTEM_PROMPT
    assert "Context shape" in SYSTEM_PROMPT
    assert "Style" in SYSTEM_PROMPT


def test_bids_prompt_documents_context_keys():
    for key in (
        "summary",
        "close_max",
        "moderate_max",
        "light_max",
        "typical_max",
        "outcome_breakdown",
        "margin_tier_breakdown",
        "competition_tier_breakdown",
        "win_rate_by_bid_type",
        "win_rate_by_estimator",
        "win_rate_by_county",
        "near_misses",
        "big_wins",
        "risk_flag_frequency",
    ):
        assert f"`{key}`" in SYSTEM_PROMPT


def test_bids_prompt_documents_severity_rubric():
    assert "`critical`" in SYSTEM_PROMPT
    assert "margin loss above the configured threshold" in SYSTEM_PROMPT
    assert "`warning`" in SYSTEM_PROMPT
    assert "competitive-density spikes" in SYSTEM_PROMPT
    assert "`info`" in SYSTEM_PROMPT
    assert "estimator performance trends" in SYSTEM_PROMPT
