"""Prompt contract tests for work-order LLM recommendations."""
from __future__ import annotations

from app.modules.work_orders.prompts import SYSTEM_PROMPT


def test_work_orders_prompt_is_not_stub():
    assert "[STUB]" not in SYSTEM_PROMPT
    assert "submit_recommendations" in SYSTEM_PROMPT
    assert "app.core.llm" in SYSTEM_PROMPT


def test_work_orders_prompt_documents_required_sections():
    assert "Quality bar:" in SYSTEM_PROMPT
    assert "Context shape" in SYSTEM_PROMPT
    assert "Style" in SYSTEM_PROMPT


def test_work_orders_prompt_documents_context_keys():
    for key in (
        "summary",
        "overdue_threshold_days",
        "status_counts",
        "avg_age_days_open",
        "overdue_count",
        "cost_vs_budget",
    ):
        assert f"`{key}`" in SYSTEM_PROMPT


def test_work_orders_prompt_documents_severity_rubric():
    assert "`critical`" in SYSTEM_PROMPT
    assert "overdue" in SYSTEM_PROMPT
    assert "over budget" in SYSTEM_PROMPT
    assert "`warning`" in SYSTEM_PROMPT
    assert "aging open work orders" in SYSTEM_PROMPT
    assert "`info`" in SYSTEM_PROMPT
    assert "mechanic" in SYSTEM_PROMPT
