"""Notification endpoints — push alerts by role, triggered from Vista events."""
from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import Optional
from agents.notifications.agent import (
    build_notification, get_notifications_for_role, mark_read,
    NotificationRole, NotificationEvent,
)

router = APIRouter()

# In-memory notification store — replace with Redis/PostgreSQL in production
_notification_store: list[dict] = []


class NotificationRequest(BaseModel):
    event: str
    payload: dict
    job_number: str = ""
    equipment_id: str = ""


class MarkReadRequest(BaseModel):
    notification_id: str
    role: str


@router.post("/")
def create_notification(req: NotificationRequest):
    """
    Create a notification for a Vista event.
    Automatically routes to the correct roles based on the event type.
    """
    try:
        event = NotificationEvent(req.event)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=400,
                            detail=f"Unknown event: {req.event}. "
                                   f"Valid events: {[e.value for e in NotificationEvent]}")

    notification = build_notification(event, req.payload,
                                       req.job_number, req.equipment_id)
    _notification_store.append(notification)
    return notification


@router.get("/")
def list_notifications(
    role: Optional[str] = Query(default=None),
    unread_only: bool = Query(default=True),
):
    """
    List notifications for a role, optionally only unread.
    role: owner | cfo | project_manager | superintendent | foreman |
          mechanic | ap_clerk | safety_officer
    """
    if role:
        try:
            r = NotificationRole(role)
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail=f"Unknown role: {role}")
        return get_notifications_for_role(r, _notification_store, unread_only)
    return _notification_store


@router.post("/mark-read")
def mark_notification_read(req: MarkReadRequest):
    """Mark a notification as read for a specific role."""
    try:
        role = NotificationRole(req.role)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Unknown role: {req.role}")

    success = mark_read(req.notification_id, role, _notification_store)
    return {"success": success}


@router.get("/events")
def list_event_types():
    """List all valid notification event types."""
    return [e.value for e in NotificationEvent]


@router.get("/roles")
def list_roles():
    """List all valid notification roles."""
    return [r.value for r in NotificationRole]
