"""
Vista Sync Service
Read-only SQL queries + REST API writes to Viewpoint Vista ERP.
Tenant-aware: each call uses the tenant's own Vista credentials.
"""
import httpx
import logging
from datetime import date, datetime
from typing import Optional
from app.core.config import settings

log = logging.getLogger("fieldbridge.vista_sync")


def _get_conn(tenant=None):
    """Get a Vista SQL connection — tenant-scoped if provided, else env config."""
    if tenant is not None:
        from app.core.tenant import get_vista_connection_for_tenant
        return get_vista_connection_for_tenant(tenant)

    import pyodbc
    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={settings.vista_sql_host},{settings.vista_sql_port};"
        f"DATABASE={settings.vista_sql_db};"
        f"UID={settings.vista_sql_user};PWD={settings.vista_sql_password};"
        f"TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str)


def _vista_post(endpoint: str, payload: dict, tenant=None) -> dict:
    """POST to Vista REST API — tenant-scoped credentials."""
    base_url = (tenant.vista_api_base_url if tenant else settings.vista_api_base_url)
    api_key = (tenant.vista_api_key if tenant else settings.vista_api_key)
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    resp = httpx.post(url, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ── READ HELPERS ─────────────────────────────────────────────────────────────

def get_equipment(equipment_id: Optional[str] = None, tenant=None) -> list[dict]:
    sql = "SELECT Equipment, Description, Category, Status, HourMeter, LastPMDate, LastPMHours, NextPMHours, Location, CostCenter FROM emem WHERE Status = 'A'"
    params = []
    if equipment_id:
        sql += " AND Equipment = ?"
        params.append(equipment_id)

    with _get_conn(tenant) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        cols = [c[0] for c in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


def get_work_orders(equipment_id: Optional[str] = None,
                    status: Optional[str] = None,
                    job_number: Optional[str] = None,
                    tenant=None) -> list[dict]:
    sql = "SELECT WorkOrder, Equipment, Description, Status, Priority, RequestedBy, OpenDate, ClosedDate, Mechanic, LaborHours, PartsCost, TotalCost, JobNumber FROM emwo WHERE 1=1"
    params = []
    if equipment_id:
        sql += " AND Equipment = ?"; params.append(equipment_id)
    if status:
        sql += " AND Status = ?"; params.append(status)
    if job_number:
        sql += " AND JobNumber = ?"; params.append(job_number)
    sql += " ORDER BY OpenDate DESC"

    with _get_conn(tenant) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        cols = [c[0] for c in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


def get_job_cost(job_number: Optional[str] = None,
                 phase: Optional[str] = None,
                 tenant=None) -> list[dict]:
    sql = """SELECT j.Job, j.Description, j.Status, j.ContractAmount,
               j.BilledToDate, j.CostToDate, j.EstimatedCost,
               i.Phase, i.CostType, i.Description AS PhaseDesc,
               i.EstimatedCost AS PhaseEst, i.ActualCost AS PhaseActual,
               i.Units, i.UnitCost
        FROM jcjm j LEFT JOIN jcci i ON j.Job = i.Job WHERE 1=1"""
    params = []
    if job_number:
        sql += " AND j.Job = ?"; params.append(job_number)
    if phase:
        sql += " AND i.Phase = ?"; params.append(phase)

    with _get_conn(tenant) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        cols = [c[0] for c in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


def get_payroll_hours(mechanic: Optional[str] = None,
                      week_ending: Optional[date] = None,
                      tenant=None) -> list[dict]:
    sql = "SELECT Employee, WeekEnding, JobNumber, Phase, CostType, Hours, PayRate, Overtime, Equipment FROM preh WHERE 1=1"
    params = []
    if mechanic:
        sql += " AND Employee = ?"; params.append(mechanic)
    if week_ending:
        sql += " AND WeekEnding = ?"; params.append(week_ending)

    with _get_conn(tenant) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        cols = [c[0] for c in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


def get_ap_vendors(vendor_id: Optional[str] = None,
                   active_only: bool = True,
                   tenant=None) -> list[dict]:
    sql = "SELECT Vendor, Name, SortName, Address1, City, State, Zip, Phone, Email, Website, Contact, Active, Notes FROM apvend WHERE 1=1"
    params = []
    if active_only:
        sql += " AND Active = 1"
    if vendor_id:
        sql += " AND Vendor = ?"; params.append(vendor_id)

    with _get_conn(tenant) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        cols = [c[0] for c in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


def get_equipment_downtime(start_date: date, end_date: date, tenant=None) -> list[dict]:
    sql = """SELECT w.Equipment, e.Description, e.Category,
               w.WorkOrder, w.Priority, w.OpenDate, w.ClosedDate,
               w.TotalCost, w.JobNumber,
               DATEDIFF(hour, w.OpenDate, ISNULL(w.ClosedDate, GETDATE())) AS DowntimeHours
        FROM emwo w JOIN emem e ON w.Equipment = e.Equipment
        WHERE w.OpenDate BETWEEN ? AND ? AND w.Priority IN ('1', '2')
        ORDER BY w.OpenDate DESC"""
    with _get_conn(tenant) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, [start_date, end_date])
        cols = [c[0] for c in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


def get_equipment_utilization(start_date: date, end_date: date, tenant=None) -> list[dict]:
    sql = """SELECT p.Equipment, e.Description, e.Category,
               SUM(p.Hours) AS BilledHours,
               COUNT(DISTINCT p.JobNumber) AS JobCount,
               SUM(p.Hours * p.UnitCost) AS BilledRevenue
        FROM preh p JOIN emem e ON p.Equipment = e.Equipment
        WHERE p.WeekEnding BETWEEN ? AND ? AND p.Equipment IS NOT NULL
        GROUP BY p.Equipment, e.Description, e.Category
        ORDER BY BilledHours DESC"""
    with _get_conn(tenant) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, [start_date, end_date])
        cols = [c[0] for c in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


# ── WRITE HELPERS ─────────────────────────────────────────────────────────────

def create_work_order(equipment: str, description: str, priority: str,
                      requested_by: str, job_number: str = "",
                      tenant=None) -> dict:
    payload = {
        "Equipment": equipment, "Description": description,
        "Priority": priority, "RequestedBy": requested_by,
        "Status": "O", "OpenDate": datetime.utcnow().isoformat(),
        "JobNumber": job_number,
    }
    result = _vista_post("/api/equipment/work-orders", payload, tenant)
    log.info(f"Created WO for {equipment}: {result.get('WorkOrder')}")
    return result


def post_payroll_record(employee: str, week_ending: str, job_number: str,
                        phase: str, cost_type: str, hours: float,
                        pay_rate: float, equipment: str = "",
                        tenant=None) -> dict:
    return _vista_post("/api/payroll/hours", {
        "Employee": employee, "WeekEnding": week_ending,
        "JobNumber": job_number, "Phase": phase, "CostType": cost_type,
        "Hours": hours, "PayRate": pay_rate, "Equipment": equipment,
    }, tenant)


def post_ap_receipt(vendor: str, invoice_number: str, invoice_date: str,
                    job_number: str, amount: float, line_items: list[dict],
                    tenant=None) -> dict:
    return _vista_post("/api/ap/receipts", {
        "Vendor": vendor, "InvoiceNumber": invoice_number,
        "InvoiceDate": invoice_date, "JobNumber": job_number,
        "Amount": amount, "LineItems": line_items,
    }, tenant)


def post_job_cost_transaction(job_number: str, phase: str, cost_type: str,
                              description: str, units: float, unit_cost: float,
                              equipment: str = "", tenant=None) -> dict:
    return _vista_post("/api/job-cost/transactions", {
        "Job": job_number, "Phase": phase, "CostType": cost_type,
        "Description": description, "Units": units, "UnitCost": unit_cost,
        "Equipment": equipment,
        "PostDate": datetime.utcnow().date().isoformat(),
    }, tenant)
