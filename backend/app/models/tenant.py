"""
Tenant model — one row per FieldBridge customer company.
VanCon Inc. is tenant_id='vancon' (the reference customer).
"""
import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum
from sqlalchemy import String, DateTime, Boolean, Enum, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class SubscriptionTier(str, PyEnum):
    STARTER = "starter"      # up to 25 equipment units — $2,500/mo
    GROWTH = "growth"        # 26–100 units — $5,000/mo
    ENTERPRISE = "enterprise"  # 100+ units — custom
    INTERNAL = "internal"    # VanCon self-use — $3,500/mo


class TenantStatus(str, PyEnum):
    ONBOARDING = "onboarding"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CHURNED = "churned"


class TenantKind(str, PyEnum):
    """What this tenant row represents.

    * ``customer`` — a paying VanCon-or-equivalent contractor running
      Vista. Default; appears in billing rollups and the tenant switcher.
    * ``shared_dataset`` — a cross-tenant data namespace
      (e.g. the NAPC bid network). Reads are open to all tenants
      via overlay-table joins. Never appears in the switcher; never
      billed. Used by Market Intel v1.5+.
    * ``internal_test`` — fixtures, integration harness, and dev
      tenants. Excluded from production rollups.
    """
    CUSTOMER = "customer"
    SHARED_DATASET = "shared_dataset"
    INTERNAL_TEST = "internal_test"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                     default=lambda: str(uuid.uuid4()))
    slug: Mapped[str] = mapped_column(String(60), unique=True, index=True,
                                       nullable=False)  # e.g. "vancon", "acme-civil"
    company_name: Mapped[str] = mapped_column(String(120), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(120), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(120), default="")

    tier: Mapped[SubscriptionTier] = mapped_column(
        Enum(SubscriptionTier), default=SubscriptionTier.STARTER)
    status: Mapped[TenantStatus] = mapped_column(
        Enum(TenantStatus), default=TenantStatus.ONBOARDING)
    kind: Mapped[TenantKind] = mapped_column(
        Enum(TenantKind),
        default=TenantKind.CUSTOMER,
        server_default=TenantKind.CUSTOMER.value,
        nullable=False,
    )

    # Vista connection — stored per tenant (encrypted at rest via Azure Key Vault in prod)
    vista_sql_host: Mapped[str] = mapped_column(String(255), default="")
    vista_sql_port: Mapped[int] = mapped_column(Integer, default=1433)
    vista_sql_db: Mapped[str] = mapped_column(String(120), default="")
    vista_sql_user: Mapped[str] = mapped_column(String(120), default="")
    vista_sql_password: Mapped[str] = mapped_column(String(255), default="")
    vista_api_base_url: Mapped[str] = mapped_column(String(255), default="")
    vista_api_key: Mapped[str] = mapped_column(String(255), default="")
    vista_connection_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # M365 / Azure per-tenant credentials
    azure_tenant_id: Mapped[str] = mapped_column(String(120), default="")
    azure_client_id: Mapped[str] = mapped_column(String(120), default="")
    azure_client_secret: Mapped[str] = mapped_column(String(255), default="")
    ap_mailbox: Mapped[str] = mapped_column(String(120), default="")
    azure_storage_connection_string: Mapped[str] = mapped_column(Text, default="")
    azure_storage_container: Mapped[str] = mapped_column(String(120), default="")

    # Fleet size — used for tier validation and billing
    equipment_unit_count: Mapped[int] = mapped_column(Integer, default=0)

    # Onboarding progress (0–5)
    onboarding_step: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    users: Mapped[list["User"]] = relationship("User", back_populates="tenant",  # noqa: F821
                                                lazy="selectin")
    usage_events: Mapped[list["UsageEvent"]] = relationship(  # noqa: F821
        "UsageEvent", back_populates="tenant", lazy="dynamic")

    @property
    def monthly_price(self) -> int:
        prices = {
            SubscriptionTier.STARTER: 2500,
            SubscriptionTier.GROWTH: 5000,
            SubscriptionTier.ENTERPRISE: 10000,
            SubscriptionTier.INTERNAL: 3500,
        }
        return prices.get(self.tier, 5000)

    def __repr__(self):
        return f"<Tenant {self.slug} ({self.tier})>"
