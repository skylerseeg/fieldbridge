"""Prompt contract tests for jobs LLM recommendations."""
from __future__ import annotations

from app.modules.jobs.prompts import SYSTEM_PROMPT


def test_jobs_prompt_is_not_stub():
    assert "[STUB]" not in SYSTEM_PROMPT
    assert "submit_recommendations" in SYSTEM_PROMPT
    assert "app.core.llm" in SYSTEM_PROMPT


def test_jobs_prompt_documents_required_sections():
    assert "Quality bar:" in SYSTEM_PROMPT
    assert "Context shape" in SYSTEM_PROMPT
    assert "Style" in SYSTEM_PROMPT


def test_jobs_prompt_documents_context_keys():
    for key in (
        "summary",
        "at_risk_days",
        "breakeven_band_pct",
        "billing_balance_pct",
        "schedule_breakdown",
        "financial_breakdown",
        "billing_metrics",
        "estimate_accuracy",
        "top_profit",
        "top_loss",
        "top_over_billed",
        "top_under_billed",
    ):
        assert f"`{key}`" in SYSTEM_PROMPT


def test_jobs_prompt_documents_severity_rubric():
    assert "`critical`" in SYSTEM_PROMPT
    assert "loss-making jobs that are also late" in SYSTEM_PROMPT
    assert "`warning`" in SYSTEM_PROMPT
    assert "at-risk schedule" in SYSTEM_PROMPT
    assert "`info`" in SYSTEM_PROMPT
    assert "margin opportunities" in SYSTEM_PROMPT
