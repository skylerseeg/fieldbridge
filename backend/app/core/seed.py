"""
Database seeder — creates the VanCon internal tenant and admin user on first run.
Run once: python -m app.core.seed
"""
import asyncio
import logging
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import AsyncSessionLocal, engine, Base
from app.core.auth import hash_password
from app.core.config import settings
from app.models.tenant import Tenant, SubscriptionTier, TenantStatus, TenantKind
from app.models.user import User, UserRole

# Importing excel_marts triggers each mart's schema.py registration against
# Base.metadata via the `mart()` helper in services/excel_marts/_base.py. Without
# this import, Base.metadata.create_all() below misses every mart_* table and
# downstream module endpoints (Equipment, Work Orders, Bids, etc.) 500 because
# they query tables that don't exist. Must run BEFORE create_all().
import app.services.excel_marts  # noqa: F401, E402

# Importing app.models registers Market Intel models (bid_event, bid_result,
# contractor) against Base.metadata. Same rationale as excel_marts above.
import app.models  # noqa: F401, E402

log = logging.getLogger("fieldbridge.seed")


# ---------------------------------------------------------------------------
# Deterministic tenant IDs — uuid.uuid5 from a fixed namespace.
#
# Reproducible across environments: same slug -> same UUID. Greppable in
# logs (paired with the slug). The shared-network tenant is a sentinel
# whose rows hold the cross-tenant bid dataset (NAPC scrapes etc.); customer
# tenants read it via ``WHERE tenant_id IN (own, shared_network)``.
#
# Historical exception: VanCon's prod row was seeded before this was
# wired, so its actual id is a random uuid4. The deterministic id below
# is what NEW deploys use; we leave the existing prod row alone — see
# docs/market-intel.md "Historical tenant ID" note.
# ---------------------------------------------------------------------------
SHARED_NETWORK_TENANT_ID = str(
    uuid.uuid5(uuid.NAMESPACE_DNS, "shared.fieldbridge.network")
)  # 7744601c-1f54-5ea4-988e-63c5e2740ee3
SHARED_NETWORK_TENANT_SLUG = "shared-network"

VANCON_DETERMINISTIC_TENANT_ID = str(
    uuid.uuid5(uuid.NAMESPACE_DNS, "vancon.fieldbridge.network")
)  # 5548b0a7-bc38-5dd2-ba4c-aef6623cee50 — used by NEW deploys only.


async def _seed_shared_network_tenant(db: AsyncSession) -> None:
    """Idempotent: create the shared-network sentinel tenant if missing.

    This is the home for the NAPC bid scrapes and any future cross-tenant
    dataset (Market Intel v1.5). Runs INDEPENDENTLY of the VanCon seed
    so it lands cleanly on environments where VanCon was already created.
    """
    result = await db.execute(
        select(Tenant).where(Tenant.slug == SHARED_NETWORK_TENANT_SLUG)
    )
    if result.scalar_one_or_none():
        log.info(
            "Shared-network tenant '%s' already exists.",
            SHARED_NETWORK_TENANT_SLUG,
        )
        return

    shared = Tenant(
        id=SHARED_NETWORK_TENANT_ID,
        slug=SHARED_NETWORK_TENANT_SLUG,
        company_name="FieldBridge Shared Bid Network",
        contact_email="market-intel@fieldbridge.io",
        contact_name="FieldBridge Internal",
        tier=SubscriptionTier.INTERNAL,
        status=TenantStatus.ACTIVE,
        kind=TenantKind.SHARED_DATASET,
        onboarding_step=5,
    )
    db.add(shared)
    await db.commit()
    log.info(
        "Seeded shared-network tenant: %s (id=%s)",
        shared.slug,
        shared.id,
    )


async def seed():
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("Tables created/verified.")

    async with AsyncSessionLocal() as db:
        # Shared-network sentinel always runs first (idempotent).
        # Customer-tenant reads union with this tenant_id for cross-tenant
        # network data (NAPC bid events etc.).
        await _seed_shared_network_tenant(db)

        # Check if VanCon tenant already exists
        result = await db.execute(
            select(Tenant).where(Tenant.slug == settings.vancon_tenant_slug)
        )
        existing = result.scalar_one_or_none()

        if existing:
            log.info(f"Tenant '{settings.vancon_tenant_slug}' already exists. Skipping seed.")
            return

        # Create VanCon as the internal reference tenant
        tenant = Tenant(
            slug=settings.vancon_tenant_slug,
            company_name="VanCon Inc.",
            contact_email=settings.fieldbridge_admin_email,
            contact_name="VanCon Admin",
            tier=SubscriptionTier.INTERNAL,
            status=TenantStatus.ACTIVE,
            onboarding_step=5,
            vista_connection_verified=False,  # will be verified when Vista creds are added
            vista_sql_host=settings.vista_sql_host,
            vista_sql_port=settings.vista_sql_port,
            vista_sql_db=settings.vista_sql_db,
            vista_sql_user=settings.vista_sql_user,
            vista_sql_password=settings.vista_sql_password,
            vista_api_base_url=settings.vista_api_base_url,
            vista_api_key=settings.vista_api_key,
            azure_tenant_id=settings.azure_tenant_id,
            azure_client_id=settings.azure_client_id,
            azure_client_secret=settings.azure_client_secret,
            ap_mailbox=settings.ap_mailbox,
            azure_storage_connection_string=settings.azure_storage_connection_string,
            azure_storage_container=settings.azure_storage_container,
        )
        db.add(tenant)
        await db.flush()

        # Create the FieldBridge super-admin user
        admin_user = User(
            tenant_id=tenant.id,
            email=settings.fieldbridge_admin_email,
            hashed_password=hash_password(settings.fieldbridge_admin_password),
            full_name="FieldBridge Admin",
            role=UserRole.FIELDBRIDGE_ADMIN,
            is_active=True,
            is_verified=True,
        )
        db.add(admin_user)
        await db.commit()

        log.info(f"Seeded tenant: {tenant.slug} (id={tenant.id})")
        log.info(f"Seeded admin: {admin_user.email}")
        log.info("Change the admin password immediately in production.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(seed())
