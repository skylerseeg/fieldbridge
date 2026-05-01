"""work_orders mart — Vista emwo shape.

No Excel ingest job: there is no source .xlsx for work orders. The Table
is registered on ``Base.metadata`` so ``create_all`` builds it, and the
:mod:`app.modules.work_orders` service reads from it directly. Vista v2
will populate this table via ``vista_sync.workorder_sync`` without
changing the schema below.
"""
from app.services.excel_marts.work_orders.schema import (
    TABLE_NAME,
    WorkOrderRow,
    table,
)

__all__ = ["TABLE_NAME", "WorkOrderRow", "table"]
