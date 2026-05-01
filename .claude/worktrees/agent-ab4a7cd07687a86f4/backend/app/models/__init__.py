# Import all models so SQLAlchemy/Alembic can discover them
from app.models.tenant import (  # noqa: F401
    Tenant,
    SubscriptionTier,
    TenantStatus,
    TenantKind,
)
from app.models.user import User, UserRole  # noqa: F401
from app.models.usage import UsageEvent, calculate_cost  # noqa: F401
from app.models.ingest_log import IngestLog  # noqa: F401
from app.models.llm_insight import LlmInsight  # noqa: F401

# Market Intel (v1.5) — public bid network dataset. Tenant-scoped, with
# a shared-dataset tenant for cross-tenant network reads. See
# ``docs/market-intel.md`` for the full design.
#
# pipeline_run is imported BEFORE bid_event / bid_result because those
# tables carry an FK ``pipeline_run_id`` → ``pipeline_runs.id``.
# SQLAlchemy resolves FKs lazily by string, but Alembic / ``create_all``
# need the target table registered first to emit DDL in the right order.
from app.models.pipeline_run import PipelineRun  # noqa: F401
from app.models.bid_event import BidEvent  # noqa: F401
from app.models.bid_result import BidResult  # noqa: F401
from app.models.contractor import Contractor  # noqa: F401
from app.models.bid_breakdown import BidBreakdown  # noqa: F401

# VANCON-internal saas module — optional, ships separately from FieldBridge
# core. If its transitive deps (bs4, etc.) aren't installed, skip silently.
try:
    from fieldbridge.saas.prospect_intelligence.models import (  # noqa: F401
        Prospect,
        ProspectContact,
    )
except ImportError:
    pass
