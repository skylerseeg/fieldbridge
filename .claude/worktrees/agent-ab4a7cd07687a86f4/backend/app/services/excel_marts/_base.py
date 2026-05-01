"""Shared helpers for excel_marts schema + ingest boilerplate.

Every mart follows the same tenant-scoped shape:
  - tenant_id (String(36), part of primary key, FK to tenants.id)
  - mart-specific columns
  - dedupe_keys is the PK set (tenant_id + natural key OR tenant_id + _row_hash)
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
)

from app.core.database import Base


def tenant_col() -> Column:
    """Standard tenant_id FK column — part of every mart PK."""
    return Column(
        "tenant_id",
        String(36),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )


def row_hash_col() -> Column:
    """Fallback composite-with-tenant_id PK for natural-keyless marts."""
    return Column("_row_hash", String(32), primary_key=True, nullable=False)


def mart(name: str, *columns: Column) -> Table:
    """Create a Table registered against the shared Base.metadata."""
    return Table(name, Base.metadata, tenant_col(), *columns)


# Re-exports so mart schema files have a one-line import.
__all__ = [
    "Base",
    "Boolean",
    "Column",
    "DateTime",
    "Float",
    "ForeignKey",
    "Index",
    "Integer",
    "String",
    "Table",
    "Text",
    "mart",
    "row_hash_col",
    "tenant_col",
]
