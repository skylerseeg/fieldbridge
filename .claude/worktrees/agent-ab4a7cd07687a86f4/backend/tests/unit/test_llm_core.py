"""Unit tests for app.core.llm.generate_insight.

We don't hit the real Anthropic API here — every test either:
  * Forces the offline-stub path by clearing settings.anthropic_api_key, or
  * Monkeypatches ``_get_client`` so the SDK call is mocked end-to-end.

The goal is to lock in:
  1. Stub fallback shape (one INFO row, ``is_stub=True``).
  2. Tool-use parsing produces a validated ``InsightResponse``.
  3. Token usage flows from the SDK response into the payload.
  4. Validation failures surface as a stub (not an exception).
  5. ``hash_data_context`` is order-stable.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.core import llm as llm_module
from app.core.llm import (
    InsightResponse,
    Severity,
    generate_insight,
    hash_data_context,
)


@pytest.fixture(autouse=True)
def reset_client(monkeypatch):
    """Each test starts with a clean cached client."""
    monkeypatch.setattr(llm_module, "_client", None)
    yield
    monkeypatch.setattr(llm_module, "_client", None)


# --------------------------------------------------------------------------- #
# hash_data_context                                                           #
# --------------------------------------------------------------------------- #


class TestHashDataContext:
    def test_stable_across_dict_order(self):
        a = hash_data_context({"x": 1, "y": [1, 2, 3]})
        b = hash_data_context({"y": [1, 2, 3], "x": 1})
        assert a == b

    def test_changes_when_value_changes(self):
        a = hash_data_context({"x": 1})
        b = hash_data_context({"x": 2})
        assert a != b

    def test_handles_datetimes_and_enums(self):
        from datetime import datetime, timezone

        h = hash_data_context(
            {
                "ts": datetime(2026, 4, 27, tzinfo=timezone.utc),
                "sev": Severity.WARNING,
            }
        )
        assert isinstance(h, str) and len(h) == 16


# --------------------------------------------------------------------------- #
# Offline stub path                                                           #
# --------------------------------------------------------------------------- #


class TestStubFallback:
    def test_empty_api_key_returns_stub(self, monkeypatch):
        monkeypatch.setattr(llm_module.settings, "anthropic_api_key", "")
        out = generate_insight(
            "equipment", {"summary": {"total_assets": 0}}, "system prompt body",
        )
        assert isinstance(out, InsightResponse)
        assert out.is_stub is True
        assert out.module == "equipment"
        assert len(out.recommendations) == 1
        assert out.recommendations[0].severity is Severity.INFO

    def test_sdk_import_failure_returns_stub(self, monkeypatch):
        monkeypatch.setattr(llm_module.settings, "anthropic_api_key", "fake-key")

        def _boom():
            raise RuntimeError("sdk missing")

        monkeypatch.setattr(llm_module, "_get_client", _boom)
        out = generate_insight("vendors", {}, "system prompt body")
        assert out.is_stub is True
        assert "SDK error" in out.recommendations[0].rationale

    def test_api_call_failure_returns_stub(self, monkeypatch):
        monkeypatch.setattr(llm_module.settings, "anthropic_api_key", "fake-key")

        class _Client:
            class messages:
                @staticmethod
                def create(**_kwargs):
                    raise RuntimeError("boom")

        monkeypatch.setattr(llm_module, "_get_client", lambda: _Client())
        out = generate_insight("equipment", {"a": 1}, "prompt")
        assert out.is_stub is True
        assert "API error" in out.recommendations[0].rationale


# --------------------------------------------------------------------------- #
# Successful tool-use path                                                    #
# --------------------------------------------------------------------------- #


def _ok_response(recommendations: list[dict[str, Any]]):
    """Build a fake Anthropic Messages API response with a tool_use block."""
    tool_block = SimpleNamespace(
        type="tool_use",
        name="submit_recommendations",
        input={"recommendations": recommendations},
    )
    usage = SimpleNamespace(
        input_tokens=120,
        output_tokens=80,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    return SimpleNamespace(content=[tool_block], usage=usage)


class TestToolUsePath:
    def test_happy_path_parses_recommendations(self, monkeypatch):
        monkeypatch.setattr(llm_module.settings, "anthropic_api_key", "fake-key")

        captured: dict[str, Any] = {}

        class _Client:
            class messages:
                @staticmethod
                def create(**kwargs):
                    captured.update(kwargs)
                    return _ok_response(
                        [
                            {
                                "title": "Retire idle excavator EX-204",
                                "severity": "warning",
                                "rationale": (
                                    "EX-204 has logged 0 tickets in the "
                                    "last 30 days while still appearing on "
                                    "the active asset list."
                                ),
                                "suggested_action": (
                                    "Have the Equipment Coordinator "
                                    "retire EX-204 and remove the rental."
                                ),
                                "affected_assets": ["EX-204"],
                            },
                        ],
                    )

        monkeypatch.setattr(llm_module, "_get_client", lambda: _Client())

        out = generate_insight(
            "equipment",
            {"summary": {"total_assets": 12}},
            "system prompt body",
        )
        assert out.is_stub is False
        assert out.module == "equipment"
        assert out.input_tokens == 120
        assert out.output_tokens == 80
        assert len(out.recommendations) == 1
        rec = out.recommendations[0]
        assert rec.title.startswith("Retire idle")
        assert rec.severity is Severity.WARNING
        assert rec.affected_assets == ["EX-204"]

        # Tool-use was forced.
        assert captured["tool_choice"]["name"] == "submit_recommendations"
        assert any(
            t["name"] == "submit_recommendations" for t in captured["tools"]
        )
        # System prompt was sent with cache_control.
        sys_blocks = captured["system"]
        assert sys_blocks[0]["cache_control"] == {"type": "ephemeral"}

    def test_validation_failure_returns_stub(self, monkeypatch):
        """Bad LLM payload — too-short title — falls back to a stub."""
        monkeypatch.setattr(llm_module.settings, "anthropic_api_key", "fake-key")

        class _Client:
            class messages:
                @staticmethod
                def create(**_kwargs):
                    return _ok_response(
                        [
                            {
                                "title": "x",  # too short
                                "severity": "info",
                                "rationale": "ok rationale long enough",
                                "suggested_action": "do it",
                                "affected_assets": [],
                            },
                        ],
                    )

        monkeypatch.setattr(llm_module, "_get_client", lambda: _Client())
        out = generate_insight("equipment", {}, "prompt")
        assert out.is_stub is True
        assert "Validation error" in out.recommendations[0].rationale

    def test_missing_tool_block_returns_stub(self, monkeypatch):
        monkeypatch.setattr(llm_module.settings, "anthropic_api_key", "fake-key")

        class _Client:
            class messages:
                @staticmethod
                def create(**_kwargs):
                    text_block = SimpleNamespace(type="text", text="hello")
                    return SimpleNamespace(content=[text_block], usage=None)

        monkeypatch.setattr(llm_module, "_get_client", lambda: _Client())
        out = generate_insight("equipment", {}, "prompt")
        assert out.is_stub is True
        assert "tool_use" in out.recommendations[0].rationale
