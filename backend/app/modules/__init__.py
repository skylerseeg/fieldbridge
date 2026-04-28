"""Customer-facing domain modules.

Each module exposes schema/service/router and is mounted at /api/<module_name>
in app.main. Modules read from the SQLite-backed Excel marts under
``app.services.excel_marts`` (the mart -> Vista v2 graduation contract is
documented in ``fieldbridge/docs/data_mapping.md``).
"""
