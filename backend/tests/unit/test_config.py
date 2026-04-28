"""Pin the env-loader contract for ``app.core.config.Settings``.

These tests exist because the env_file resolution silently broke once
already (was a relative ``".env"`` string) and the failure mode was
indirect — Phase-6 LLM insights served the stub response because
``ANTHROPIC_API_KEY`` never made it into ``Settings``. Pin the two
guarantees that fix relied on so a future refactor can't silently
regress them again.
"""
from __future__ import annotations

import os
from pathlib import Path

from app.core import config as config_module


def test_env_file_paths_are_absolute() -> None:
    """``env_file`` must resolve to absolute paths.

    Relative paths break when the process CWD isn't ``backend/``,
    which happens in docker-compose, pytest-from-repo-root, and any
    subprocess that inherits a different CWD.
    """
    env_files = config_module._ENV_FILES
    assert isinstance(env_files, tuple)
    assert len(env_files) >= 1
    for p in env_files:
        assert isinstance(p, str)
        assert os.path.isabs(p), f"env_file entry not absolute: {p!r}"


def test_env_file_paths_target_expected_locations() -> None:
    """The two candidates are ``fieldbridge/.env`` and ``fieldbridge/backend/.env``.

    Anchored on this file's location so the test moves with the repo.
    """
    backend_dir = Path(__file__).resolve().parents[2]
    repo_parent = backend_dir.parent

    env_files = set(config_module._ENV_FILES)
    assert str(repo_parent / ".env") in env_files
    assert str(backend_dir / ".env") in env_files


def test_settings_ignores_unknown_env_keys(monkeypatch) -> None:
    """``extra='ignore'`` must hold so unrelated keys don't crash boot.

    The shared ``fieldbridge/.env`` carries frontend (NEXTAUTH_*), n8n,
    and AP-mailbox keys that aren't part of the backend ``Settings``
    model. Boot must not refuse them.
    """
    monkeypatch.setenv("FIELDBRIDGE_NOT_A_REAL_SETTING", "value")
    monkeypatch.setenv("NEXTAUTH_URL", "https://example.test")
    monkeypatch.setenv("NEXTAUTH_SECRET", "irrelevant")

    # Construct fresh — should not raise on the unknown keys.
    s = config_module.Settings()
    assert s.environment in {"development", "staging", "production", "test"}


def test_cors_allowed_origins_default() -> None:
    """Default keeps localhost:3000 — preserves dev backward-compat
    when no env var is set."""
    s = config_module.Settings()
    assert s.cors_allowed_origins == ["http://localhost:3000"]


def test_cors_allowed_origins_parses_csv_env(monkeypatch) -> None:
    """Comma-separated env values must split into a list.

    The Render production env will set this as
    ``CORS_ALLOWED_ORIGINS=https://fieldbridge.vercel.app,http://localhost:3000``.
    Without ``NoDecode`` on the field annotation, pydantic-settings
    would attempt JSON-decoding and raise on the comma-separated form.
    """
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS",
        "https://fieldbridge.vercel.app,http://localhost:3000",
    )
    s = config_module.Settings()
    assert s.cors_allowed_origins == [
        "https://fieldbridge.vercel.app",
        "http://localhost:3000",
    ]


def test_cors_allowed_origins_strips_whitespace_and_empties(monkeypatch) -> None:
    """Tolerate sloppy operator input — trailing commas, surrounding
    whitespace. Avoids "I added a space and now CORS rejects everything"
    debugging at 2am."""
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS",
        "  https://a.com  ,  https://b.com  ,",
    )
    s = config_module.Settings()
    assert s.cors_allowed_origins == ["https://a.com", "https://b.com"]
