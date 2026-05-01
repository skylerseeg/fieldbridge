# Import all models so SQLAlchemy/Alembic can discover them
from app.models.tenant import Tenant, SubscriptionTier, TenantStatus  # noqa: F401
from app.models.user import User, UserRole  # noqa: F401
from app.models.usage import UsageEvent, calculate_cost  # noqa: F401
from app.models.ingest_log import IngestLog  # noqa: F401
from app.models.llm_insight import LlmInsight  # noqa: F401

# VANCON-internal saas module — optional, ships separately from FieldBridge
# core. If its transitive deps (bs4, etc.) aren't installed, skip silently.
try:
    from fieldbridge.saas.prospect_intelligence.models import (  # noqa: F401
        Prospect,
        ProspectContact,
    )
except ImportError:
    pass
