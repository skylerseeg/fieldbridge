"""
Tenant context helpers.
Provides per-tenant Vista credentials and isolated service configurations.
"""
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.tenant import Tenant


async def get_tenant_by_slug(slug: str, db: AsyncSession) -> Optional[Tenant]:
    result = await db.execute(select(Tenant).where(Tenant.slug == slug))
    return result.scalar_one_or_none()


async def get_tenant_by_id(tenant_id: str, db: AsyncSession) -> Optional[Tenant]:
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    return result.scalar_one_or_none()


def get_vista_connection_for_tenant(tenant: Tenant):
    """
    Return a pyodbc connection scoped to this tenant's Vista instance.
    Each customer has their own Vista SQL Server credentials.
    """
    import pyodbc
    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={tenant.vista_sql_host},{tenant.vista_sql_port};"
        f"DATABASE={tenant.vista_sql_db};"
        f"UID={tenant.vista_sql_user};"
        f"PWD={tenant.vista_sql_password};"
        f"TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str, timeout=10)


def get_chromadb_collection_name(tenant: Tenant) -> str:
    """Each tenant gets their own isolated ChromaDB collection."""
    return f"{tenant.slug}_projects"


def get_blob_container_name(tenant: Tenant) -> str:
    """Each tenant gets their own Azure Blob container."""
    return tenant.azure_storage_container or f"fieldbridge-{tenant.slug}"


def test_vista_connection(tenant: Tenant) -> dict:
    """
    Test a tenant's Vista SQL connection. Returns success/error dict.
    Used in the onboarding wizard Step 2.
    """
    if not tenant.vista_sql_host:
        return {"success": False, "error": "Vista SQL host not configured"}
    try:
        conn = get_vista_connection_for_tenant(tenant)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM emem WHERE Status = 'A'")
        count = cursor.fetchone()[0]
        conn.close()
        return {
            "success": True,
            "active_equipment_count": count,
            "message": f"Connected successfully. Found {count} active equipment records.",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def test_vista_api(tenant: Tenant) -> dict:
    """Test the Vista REST API connection using the tenant's API key."""
    if not tenant.vista_api_base_url:
        return {"success": False, "error": "Vista API URL not configured"}
    try:
        import httpx
        url = f"{tenant.vista_api_base_url.rstrip('/')}/api/health"
        headers = {"X-API-Key": tenant.vista_api_key}
        resp = httpx.get(url, headers=headers, timeout=10)
        return {
            "success": resp.status_code < 400,
            "status_code": resp.status_code,
            "message": "Vista API reachable" if resp.status_code < 400 else resp.text,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
