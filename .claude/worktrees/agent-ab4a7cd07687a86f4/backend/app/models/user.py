"""
User model — employees of a tenant who can log into FieldBridge.
Roles mirror the notification roles in the agents layer.
"""
import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum
from sqlalchemy import String, DateTime, Boolean, Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class UserRole(str, PyEnum):
    OWNER = "owner"                  # company owner — full access
    CFO = "cfo"                      # financials + dashboard
    PROJECT_MANAGER = "project_manager"
    SUPERINTENDENT = "superintendent"
    FOREMAN = "foreman"
    MECHANIC = "mechanic"
    AP_CLERK = "ap_clerk"
    SAFETY_OFFICER = "safety_officer"
    FIELDBRIDGE_ADMIN = "fieldbridge_admin"  # VANCON Technologies staff


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                     default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36),
                                            ForeignKey("tenants.id", ondelete="CASCADE"),
                                            nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(120), unique=True,
                                        nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[UserRole] = mapped_column(Enum(UserRole),
                                            default=UserRole.PROJECT_MANAGER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc))
    last_login: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="users")  # noqa: F821

    def __repr__(self):
        return f"<User {self.email} [{self.role}] @ {self.tenant_id}>"
