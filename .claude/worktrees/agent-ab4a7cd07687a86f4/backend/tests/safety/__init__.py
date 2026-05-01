"""Safety / lint tests that run as part of the regular pytest suite.

These tests fail when a production source file ships an unsafe pattern
(raw f-string SQL, eval, hardcoded secrets, etc.). Keeping the lint in
pytest — instead of a separate ruff plugin — means a contributor sees
the same red signal whether they break a unit test or a safety rule.
"""

from __future__ import annotations
