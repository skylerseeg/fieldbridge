"""
Prospect and Contact models for VANCON Technologies sales pipeline.
"""
import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum
from sqlalchemy import String, DateTime, Boolean, Enum, Text, Integer, Float, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class ProspectStatus(str, PyEnum):
    IDENTIFIED = "identified"       # in our list, not yet contacted
    RESEARCHED = "researched"       # website scraped, intel gathered
    ENRICHED = "enriched"           # contacts found via Apollo
    OUTREACH_READY = "outreach_ready"  # ready for Buck to call
    CONTACTED = "contacted"         # first contact made
    DEMO_SCHEDULED = "demo_scheduled"
    DEMO_DONE = "demo_done"
    PROPOSAL_SENT = "proposal_sent"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"
    NOT_QUALIFIED = "not_qualified"


class ProspectTier(str, PyEnum):
    TIER_1 = "tier_1"   # $50M-$200M revenue, confirmed Vista, heavy civil
    TIER_2 = "tier_2"   # $20M-$50M revenue, likely Vista, heavy civil
    TIER_3 = "tier_3"   # $10M-$20M revenue, smaller but right profile


class Prospect(Base):
    __tablename__ = "prospects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                     default=lambda: str(uuid.uuid4()))
    company_name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    website: Mapped[str] = mapped_column(String(255), default="")
    domain: Mapped[str] = mapped_column(String(120), default="", index=True)

    # Location
    city: Mapped[str] = mapped_column(String(80), default="")
    state: Mapped[str] = mapped_column(String(4), default="")
    region: Mapped[str] = mapped_column(String(60), default="")

    # Company profile
    estimated_revenue_min: Mapped[float] = mapped_column(Float, default=0)
    estimated_revenue_max: Mapped[float] = mapped_column(Float, default=0)
    employee_count_est: Mapped[int] = mapped_column(Integer, default=0)
    equipment_fleet_est: Mapped[int] = mapped_column(Integer, default=0)

    # Vista/Trimble fit
    uses_vista: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    uses_trimble: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    vista_confirmed_source: Mapped[str] = mapped_column(String(120), default="")

    # Work types (from website scrape)
    does_earthwork: Mapped[bool] = mapped_column(Boolean, default=False)
    does_utilities: Mapped[bool] = mapped_column(Boolean, default=False)
    does_paving: Mapped[bool] = mapped_column(Boolean, default=False)
    does_bridges: Mapped[bool] = mapped_column(Boolean, default=False)
    does_wastewater: Mapped[bool] = mapped_column(Boolean, default=False)
    does_water: Mapped[bool] = mapped_column(Boolean, default=False)
    does_site_development: Mapped[bool] = mapped_column(Boolean, default=False)

    # Intelligence from scrape
    about_summary: Mapped[str] = mapped_column(Text, default="")
    services_raw: Mapped[str] = mapped_column(Text, default="")
    projects_mentioned: Mapped[str] = mapped_column(Text, default="")
    technology_mentions: Mapped[str] = mapped_column(Text, default="")
    pain_point_signals: Mapped[str] = mapped_column(Text, default="")  # JSON list
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Scoring (0-100)
    fit_score: Mapped[int] = mapped_column(Integer, default=0)
    priority_tier: Mapped[ProspectTier] = mapped_column(
        Enum(ProspectTier), default=ProspectTier.TIER_2)

    # Pipeline
    status: Mapped[ProspectStatus] = mapped_column(
        Enum(ProspectStatus), default=ProspectStatus.IDENTIFIED)
    assigned_to: Mapped[str] = mapped_column(String(80), default="Buck")
    notes: Mapped[str] = mapped_column(Text, default="")
    last_contacted: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    next_follow_up: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    # Source
    source: Mapped[str] = mapped_column(String(60), default="seed_list")
    apollo_org_id: Mapped[str] = mapped_column(String(60), default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc))

    contacts: Mapped[list["ProspectContact"]] = relationship(
        "ProspectContact", back_populates="prospect", lazy="selectin")

    __table_args__ = (
        Index("ix_prospect_state_score", "state", "fit_score"),
        Index("ix_prospect_status_tier", "status", "priority_tier"),
    )

    @property
    def estimated_arr(self) -> float:
        """Estimated ARR if they close — based on fleet size."""
        fleet = self.equipment_fleet_est or 50
        if fleet <= 25:
            return 30_000
        elif fleet <= 100:
            return 60_000
        else:
            return 120_000

    def __repr__(self):
        return f"<Prospect {self.company_name} [{self.state}] score={self.fit_score}>"


class ContactRole(str, PyEnum):
    CEO = "CEO"
    PRESIDENT = "President"
    COO = "COO"
    CFO = "CFO"
    CTO = "CTO"
    VP_OPERATIONS = "VP Operations"
    VP_TECHNOLOGY = "VP Technology"
    DIRECTOR_IT = "Director of IT"
    CONTROLLER = "Controller"
    PROJECT_EXECUTIVE = "Project Executive"
    EQUIPMENT_MANAGER = "Equipment Manager"
    OTHER = "Other"


class ProspectContact(Base):
    __tablename__ = "prospect_contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                     default=lambda: str(uuid.uuid4()))
    prospect_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("prospects.id", ondelete="CASCADE"),
        nullable=False, index=True)

    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(120), default="")
    role_category: Mapped[ContactRole] = mapped_column(
        Enum(ContactRole), default=ContactRole.OTHER)
    email: Mapped[str] = mapped_column(String(120), default="", index=True)
    phone: Mapped[str] = mapped_column(String(30), default="")
    linkedin_url: Mapped[str] = mapped_column(String(255), default="")

    is_decision_maker: Mapped[bool] = mapped_column(Boolean, default=False)
    is_primary_contact: Mapped[bool] = mapped_column(Boolean, default=False)

    # Apollo enrichment metadata
    apollo_person_id: Mapped[str] = mapped_column(String(60), default="")
    email_confidence: Mapped[int] = mapped_column(Integer, default=0)  # 0-100

    source: Mapped[str] = mapped_column(String(30), default="apollo")
    enriched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    prospect: Mapped["Prospect"] = relationship("Prospect", back_populates="contacts")

    __table_args__ = (
        Index("ix_contact_prospect_dm", "prospect_id", "is_decision_maker"),
    )

    def __repr__(self):
        return f"<Contact {self.full_name} [{self.title}]>"
