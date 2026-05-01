import os
import pyodbc
from dotenv import load_dotenv

load_dotenv()

host = os.getenv("VISTA_SQL_HOST")
port = os.getenv("VISTA_SQL_PORT", "1433")
user = os.getenv("VISTA_SQL_USER")
password = os.getenv("VISTA_SQL_PASSWORD")

conn_str = (
    f"DRIVER={{ODBC Driver 18 for SQL Server}};"
    f"SERVER={host},{port};"
    f"UID={user};PWD={password};"
    f"Encrypt=yes;"
    f"TrustServerCertificate=yes;"
)

print(f"Connecting to {host}:{port} as {user}...")

try:
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sys.databases WHERE database_id > 4;")
    print("\nUser databases on this server:")
    for row in cursor.fetchall():
        print(f"  - {row.name}")
    conn.close()
except pyodbc.Error as e:
    print(f"\nConnection failed:\n{e}")