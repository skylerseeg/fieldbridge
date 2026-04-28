"""Prompt contract tests for timecards LLM recommendations."""
from __future__ import annotations

from app.modules.timecards.prompts import SYSTEM_PROMPT


def test_timecards_prompt_is_not_stub():
    assert "[STUB]" not in SYSTEM_PROMPT
    assert "submit_recommendations" in SYSTEM_PROMPT
    assert "app.core.llm" in SYSTEM_PROMPT


def test_timecards_prompt_documents_required_sections():
    assert "Quality bar:" in SYSTEM_PROMPT
    assert "Context shape" in SYSTEM_PROMPT
    assert "Style" in SYSTEM_PROMPT


def test_timecards_prompt_documents_context_keys():
    for key in (
        "summary",
        "variance_band_pct",
        "variance_over",
        "variance_under",
        "overtime_leaders",
        "overhead_ratio",
    ):
        assert f"`{key}`" in SYSTEM_PROMPT


def test_timecards_prompt_documents_severity_rubric():
    assert "`critical`" in SYSTEM_PROMPT
    assert "FTE projection-vs-actual blowouts" in SYSTEM_PROMPT
    assert "`warning`" in SYSTEM_PROMPT
    assert "overtime concentration" in SYSTEM_PROMPT
    assert "`info`" in SYSTEM_PROMPT
    assert "forecast adjustments" in SYSTEM_PROMPT
