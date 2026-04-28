"""
Notifications Service  (Domain 6)
Role-based push notifications triggered by Vista events.
Nobody has a reliable, role-based system tied to Vista state — FieldBridge does.
"""
import json
import logging
from datetime import datetime, timezone
from enum import Enum

log = logging.getLogger("fieldbridge.notifications")


class NotificationRole(str, Enum):
    OWNER = "owner"
    CFO = "cfo"
    PROJECT_MANAGER = "project_manager"
    SUPERINTENDENT = "superintendent"
    FOREMAN = "foreman"
    MECHANIC = "mechanic"
    AP_CLERK = "ap_clerk"
    SAFETY_OFFICER = "safety_officer"


class NotificationEvent(str, Enum):
    # Equipment
    WORK_ORDER_CREATED = "work_order_created"
    EQUIPMENT_DOWN = "equipment_down"
    PM_OVERDUE = "pm_overdue"
    PREDICTIVE_ALERT = "predictive_alert"
    # Cost
    JOB_COST_OVERRUN = "job_cost_overrun"
    INVOICE_PROCESSED = "invoice_processed"
    DOWNTIME_COST_ALERT = "downtime_cost_alert"
    # Operations
    ASSET_MOVED = "asset_moved"
    TRANSPORT_SCHEDULED = "transport_scheduled"
    PERMIT_REQUIRED = "permit_required"
    # Safety
    INCIDENT_LOGGED = "incident_logged"
    SAFETY_FLAG = "safety_flag"
    RECORDABLE_INCIDENT = "recordable_incident"
    # Financial
    PAYROLL_SUBMITTED = "payroll_submitted"
    PAYROLL_FLAG = "payroll_flag"
    # Reporting
    DAILY_DASHBOARD = "daily_dashboard"
    WEEKLY_RECOMMENDATIONS = "weekly_recommendations"


# Role → event routing table
# Defines which roles receive which event types
ROLE_EVENT_MAP: dict[NotificationEvent, list[NotificationRole]] = {
    NotificationEvent.WORK_ORDER_CREATED: [
        NotificationRole.MECHANIC, NotificationRole.SUPERINTENDENT],
    NotificationEvent.EQUIPMENT_DOWN: [
        NotificationRole.SUPERINTENDENT, NotificationRole.PROJECT_MANAGER,
        NotificationRole.MECHANIC],
    NotificationEvent.PM_OVERDUE: [
        NotificationRole.MECHANIC, NotificationRole.SUPERINTENDENT],
    NotificationEvent.PREDICTIVE_ALERT: [
        NotificationRole.MECHANIC, NotificationRole.SUPERINTENDENT],
    NotificationEvent.JOB_COST_OVERRUN: [
        NotificationRole.PROJECT_MANAGER, NotificationRole.CFO,
        NotificationRole.OWNER],
    NotificationEvent.INVOICE_PROCESSED: [
        NotificationRole.AP_CLERK, NotificationRole.PROJECT_MANAGER],
    NotificationEvent.DOWNTIME_COST_ALERT: [
        NotificationRole.PROJECT_MANAGER, NotificationRole.CFO],
    NotificationEvent.ASSET_MOVED: [
        NotificationRole.SUPERINTENDENT, NotificationRole.FOREMAN],
    NotificationEvent.TRANSPORT_SCHEDULED: [
        NotificationRole.SUPERINTENDENT, NotificationRole.FOREMAN],
    NotificationEvent.PERMIT_REQUIRED: [
        NotificationRole.SUPERINTENDENT, NotificationRole.PROJECT_MANAGER],
    NotificationEvent.INCIDENT_LOGGED: [
        NotificationRole.SAFETY_OFFICER, NotificationRole.PROJECT_MANAGER,
        NotificationRole.SUPERINTENDENT],
    NotificationEvent.SAFETY_FLAG: [
        NotificationRole.SAFETY_OFFICER, NotificationRole.SUPERINTENDENT],
    NotificationEvent.RECORDABLE_INCIDENT: [
        NotificationRole.SAFETY_OFFICER, NotificationRole.OWNER,
        NotificationRole.CFO],
    NotificationEvent.PAYROLL_SUBMITTED: [
        NotificationRole.AP_CLERK, NotificationRole.PROJECT_MANAGER],
    NotificationEvent.PAYROLL_FLAG: [
        NotificationRole.AP_CLERK, NotificationRole.PROJECT_MANAGER],
    NotificationEvent.DAILY_DASHBOARD: [
        NotificationRole.OWNER, NotificationRole.CFO,
        NotificationRole.PROJECT_MANAGER],
    NotificationEvent.WEEKLY_RECOMMENDATIONS: [
        NotificationRole.OWNER, NotificationRole.CFO],
}


def build_notification(event: NotificationEvent, payload: dict,
                       job_number: str = "", equipment_id: str = "") -> dict:
    """
    Build a notification record for a Vista event.

    Returns notification dict with target roles, message, and metadata.
    """
    target_roles = ROLE_EVENT_MAP.get(event, [])
    message = _format_message(event, payload)

    return {
        "id": f"{event.value}_{datetime.now(tz=timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "event": event.value,
        "message": message,
        "target_roles": [r.value for r in target_roles],
        "job_number": job_number,
        "equipment_id": equipment_id,
        "payload": payload,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "read_by": [],
    }


def _format_message(event: NotificationEvent, payload: dict) -> str:
    """Format a human-readable notification message for each event type."""
    templates = {
        NotificationEvent.WORK_ORDER_CREATED: (
            "New WO #{work_order} — {equipment}: {description} (Priority {priority})"
        ),
        NotificationEvent.EQUIPMENT_DOWN: (
            "EQUIPMENT DOWN: {equipment} — {description}. Job {job_number} affected."
        ),
        NotificationEvent.PM_OVERDUE: (
            "PM OVERDUE: {equipment} is {hours_overdue:.0f} hours past scheduled service."
        ),
        NotificationEvent.PREDICTIVE_ALERT: (
            "PREDICTIVE: {equipment} — {component_at_risk} at {risk_level} risk. "
            "Action needed within {urgency_days} days."
        ),
        NotificationEvent.JOB_COST_OVERRUN: (
            "COST ALERT: Job {job_number} is ${overrun_amount:,.0f} over budget "
            "({overrun_pct:.1f}%)."
        ),
        NotificationEvent.INCIDENT_LOGGED: (
            "INCIDENT: {osha_classification} on Job {job_number}. "
            "Review corrective actions."
        ),
        NotificationEvent.RECORDABLE_INCIDENT: (
            "RECORDABLE INCIDENT on Job {job_number}. "
            "Regulatory reporting may be required within {reporting_deadline_hours} hours."
        ),
        NotificationEvent.DAILY_DASHBOARD: (
            "Daily executive dashboard for {period} is ready."
        ),
        NotificationEvent.DOWNTIME_COST_ALERT: (
            "DOWNTIME COST: Fleet downtime this period cost ${total_downtime_cost:,.0f}."
        ),
    }

    template = templates.get(event, f"Event: {event.value}")
    try:
        return template.format(**payload)
    except (KeyError, ValueError):
        return f"{event.value}: {json.dumps(payload, default=str)[:200]}"


def get_notifications_for_role(role: NotificationRole,
                                notification_store: list[dict],
                                unread_only: bool = True) -> list[dict]:
    """Filter notification store to messages relevant for a given role."""
    result = []
    for n in notification_store:
        if role.value not in n.get("target_roles", []):
            continue
        if unread_only and role.value in n.get("read_by", []):
            continue
        result.append(n)
    return sorted(result, key=lambda x: x.get("created_at", ""), reverse=True)


def mark_read(notification_id: str, role: NotificationRole,
              notification_store: list[dict]) -> bool:
    """Mark a notification as read for a role."""
    for n in notification_store:
        if n.get("id") == notification_id:
            if role.value not in n.get("read_by", []):
                n.setdefault("read_by", []).append(role.value)
            return True
    return False
