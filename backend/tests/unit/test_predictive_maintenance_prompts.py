"""Prompt contract tests for predictive-maintenance LLM recommendations."""
from __future__ import annotations

from app.modules.predictive_maintenance.prompts import SYSTEM_PROMPT


def test_predictive_maintenance_prompt_is_not_stub():
    assert "[STUB]" not in SYSTEM_PROMPT
    assert "submit_recommendations" in SYSTEM_PROMPT
    assert "app.core.llm" in SYSTEM_PROMPT


def test_predictive_maintenance_prompt_documents_required_sections():
    assert "Quality bar:" in SYSTEM_PROMPT
    assert "Context shape" in SYSTEM_PROMPT
    assert "Style" in SYSTEM_PROMPT


def test_predictive_maintenance_prompt_documents_context_keys():
    for key in (
        "summary",
        "risk_tier_breakdown",
        "status_breakdown",
        "source_breakdown",
        "failure_mode_breakdown",
        "aging_breakdown",
        "top_equipment_exposure",
        "failure_mode_impact",
        "top_by_exposure",
        "recent_completions",
    ):
        assert f"`{key}`" in SYSTEM_PROMPT


def test_predictive_maintenance_prompt_documents_severity_rubric():
    assert "`critical`" in SYSTEM_PROMPT
    assert "open_overdue_count" in SYSTEM_PROMPT
    assert "open_critical_count" in SYSTEM_PROMPT
    assert "`warning`" in SYSTEM_PROMPT
    assert "total_estimated_exposure" in SYSTEM_PROMPT
    assert "`info`" in SYSTEM_PROMPT
    assert "pm_overdue" in SYSTEM_PROMPT
