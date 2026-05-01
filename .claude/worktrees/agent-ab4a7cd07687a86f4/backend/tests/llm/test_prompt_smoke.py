"""Smoke tests for every module's `prompts.py`.

The contract a *live* SYSTEM_PROMPT must satisfy:

  1. **role**         — opens with "You are FieldBridge's ..." so the
                        agent knows the domain it's playing.
  2. **quality bar**  — explicit "Quality bar:" section, otherwise the
                        agent freelances and produces fluff.
  3. **context shape**— named "Context shape" section that documents
                        the top-level JSON keys the agent will see.
  4. **style**        — named "Style" section that pins down title /
                        rationale / suggested-action voice.
  5. **tool ref**     — references `submit_recommendations` so the
                        prompt is wired to the canonical Phase-6 tool
                        contract from `app.core.llm`.

Stub prompts (still placeholders, owned by the LLM Prompts Worker)
are skipped on the section assertions but must still:

  * import cleanly,
  * expose a non-empty SYSTEM_PROMPT string, and
  * self-identify with a "[STUB]" marker so tests/CI know to skip.

This catches the exact regression the user worried about: an LLM
worker fills in a stub but forgets one of the canonical sections.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest


pytestmark = pytest.mark.llm


MODULE_PROMPTS_ROOT = Path(__file__).resolve().parents[2] / "app" / "modules"


def _discover_prompt_modules() -> list[str]:
    """Find every `app.modules.<name>.prompts` we should exercise."""
    out: list[str] = []
    for prompts_path in sorted(MODULE_PROMPTS_ROOT.glob("*/prompts.py")):
        module_dir = prompts_path.parent.name
        out.append(f"app.modules.{module_dir}.prompts")
    return out


PROMPT_MODULES = _discover_prompt_modules()


REQUIRED_SECTIONS: dict[str, re.Pattern[str]] = {
    "role": re.compile(r"You are FieldBridge['’]s\s+", re.IGNORECASE),
    "quality_bar": re.compile(r"Quality bar\s*:?", re.IGNORECASE),
    "context_shape": re.compile(r"Context shape", re.IGNORECASE),
    "style": re.compile(r"\bStyle\b\s*\n\s*-{3,}", re.IGNORECASE),
    "tool_ref": re.compile(r"submit_recommendations"),
}

STUB_MARKER = re.compile(r"\[STUB\]", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Discovery sanity                                                            #
# --------------------------------------------------------------------------- #


def test_at_least_one_prompts_module_discovered():
    """If this fails we're not actually scanning anything."""
    assert PROMPT_MODULES, "no app.modules.*.prompts modules found"


# --------------------------------------------------------------------------- #
# Per-module contract                                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("dotted", PROMPT_MODULES)
class TestPromptContract:
    def test_imports_cleanly(self, dotted: str):
        importlib.import_module(dotted)

    def test_exposes_system_prompt_str(self, dotted: str):
        mod = importlib.import_module(dotted)

        assert hasattr(mod, "SYSTEM_PROMPT"), f"{dotted} is missing SYSTEM_PROMPT"
        sp = getattr(mod, "SYSTEM_PROMPT")
        assert isinstance(sp, str), f"{dotted}.SYSTEM_PROMPT must be str, got {type(sp).__name__}"
        assert sp.strip(), f"{dotted}.SYSTEM_PROMPT is empty"

    def test_canonical_sections_when_live(self, dotted: str):
        """Filled-in prompts must contain every canonical section.

        Stubs are explicitly skipped — but the moment a stub loses its
        [STUB] marker (because someone implemented it) this test starts
        enforcing the full contract. That's the regression catcher.
        """
        mod = importlib.import_module(dotted)
        sp: str = getattr(mod, "SYSTEM_PROMPT")

        if STUB_MARKER.search(sp):
            pytest.skip(f"{dotted} is still a stub")

        missing = [
            section for section, pattern in REQUIRED_SECTIONS.items() if not pattern.search(sp)
        ]
        assert not missing, (
            f"{dotted}.SYSTEM_PROMPT is missing required canonical "
            f"sections: {missing}. "
            "See tests/llm/test_prompt_smoke.py for the contract."
        )


# --------------------------------------------------------------------------- #
# Coverage report — purely informational                                      #
# --------------------------------------------------------------------------- #


def test_prompt_implementation_coverage(capsys: pytest.CaptureFixture):
    """Print which prompts are live vs. stub. Always passes — purely a
    visibility test for CI logs so the LLM Prompts Worker can see the
    burn-down."""
    live: list[str] = []
    stubs: list[str] = []

    for dotted in PROMPT_MODULES:
        mod = importlib.import_module(dotted)
        sp = getattr(mod, "SYSTEM_PROMPT", "")
        if STUB_MARKER.search(sp):
            stubs.append(dotted)
        else:
            live.append(dotted)

    total = len(PROMPT_MODULES)
    pct = (len(live) / total * 100) if total else 0.0
    with capsys.disabled():
        print(f"\n[prompt-smoke] live={len(live)}/{total} ({pct:.0f}%)")
        for d in live:
            print(f"  + {d}")
        for d in stubs:
            print(f"  · {d} (stub)")

    assert total > 0
