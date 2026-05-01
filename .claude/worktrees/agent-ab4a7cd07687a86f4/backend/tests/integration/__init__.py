"""Cross-module integration tests + the shared harness factory.

Module workers can `from tests.integration.harness import integrated_engine`
to spin up a SQLite database with every mart Table from
`app.services.excel_marts` registered + a known tenant seeded.

This package is owned by the Tests/CI Worker. Module-specific
integration suites still belong in `tests/integration/test_<module>_*.py`
under the **module worker's** authorship, but the *harness itself*
(fixtures, seeders, schema bootstrap) is centralized here so a new
mart only requires adding it to `app.services.excel_marts.__init__` —
the harness picks it up via `Base.metadata`.
"""

from __future__ import annotations
