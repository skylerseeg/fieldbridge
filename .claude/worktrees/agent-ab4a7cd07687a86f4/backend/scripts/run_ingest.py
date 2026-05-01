"""Thin wrapper around app.core.ingest.main().

Running ``python -m app.core.ingest`` makes that module ``__main__``, which
breaks ``register_job()`` side effects: each mart does
``from app.core.ingest import register_job`` and ends up with a *second* copy
of the module (the non-__main__ one), so the registry the CLI sees is empty.
Running through this wrapper imports ``app.core.ingest`` as a normal module,
so everyone shares the same ``_REGISTRY``.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.core.ingest import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
