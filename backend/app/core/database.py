from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.core.config import settings

engine = create_async_engine(
    settings.database_url.replace("postgresql://", "postgresql+asyncpg://"),
    echo=(settings.environment == "development"),
    pool_pre_ping=True,
)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

def get_vista_connection():
    """Synchronous read-only connection to Vista SQL Server via pyodbc."""
    import pyodbc
    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={settings.vista_sql_host},{settings.vista_sql_port};"
        f"DATABASE={settings.vista_sql_db};"
        f"UID={settings.vista_sql_user};PWD={settings.vista_sql_password};"
        f"TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str)
