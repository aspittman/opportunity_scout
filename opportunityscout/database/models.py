"""SQLite schema. All timestamps are naive UTC; presentation uses Mountain time."""
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Opportunity(Base):
    __tablename__ = 'opportunities'
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(500))
    organization: Mapped[str] = mapped_column(String(300), default='')
    category: Mapped[str] = mapped_column(String(200), default='')
    location: Mapped[str] = mapped_column(String(500), default='')
    remote: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    url: Mapped[str] = mapped_column(Text, default='')
    description: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(40), default='New')
    event_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    event_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    admission_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_audience: Mapped[str] = mapped_column(Text, default='')
    industries: Mapped[str] = mapped_column(Text, default='')
    employment_value: Mapped[str] = mapped_column(Text, default='Unknown; evaluate before attending.')
    business_value: Mapped[str] = mapped_column(Text, default='Unknown; evaluate before attending.')
    compensation_type: Mapped[str] = mapped_column(String(20), default='unknown')
    compensation_text: Mapped[str] = mapped_column(Text, default='Unknown')
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    pay_basis: Mapped[str] = mapped_column(String(30), default='unknown')
    work_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    travel_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    preparation_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    expenses: Mapped[float | None] = mapped_column(Float, nullable=True)
    annual_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    weekly_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_miles: Mapped[float | None] = mapped_column(Float, nullable=True)
    arrangement: Mapped[str] = mapped_column(String(100), default='')
    flexible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    score: Mapped[float] = mapped_column(Float, default=0)
    score_details: Mapped[dict] = mapped_column(JSON, default=dict)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_verified: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sources: Mapped[list['Source']] = relationship(cascade='all, delete-orphan')
    history: Mapped[list['StatusChange']] = relationship(cascade='all, delete-orphan', order_by='StatusChange.at')
    notes: Mapped[list['Note']] = relationship(cascade='all, delete-orphan', order_by='Note.at')


class Source(Base):
    __tablename__ = 'sources'
    __table_args__ = (UniqueConstraint('provider', 'source_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey('opportunities.id'))
    provider: Mapped[str] = mapped_column(String(100))
    source_id: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class StatusChange(Base):
    __tablename__ = 'status_changes'
    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey('opportunities.id'))
    old_status: Mapped[str] = mapped_column(String(40), default='')
    new_status: Mapped[str] = mapped_column(String(40))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Note(Base):
    __tablename__ = 'notes'
    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey('opportunities.id'))
    text: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Contact(Base):
    __tablename__ = 'contacts'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    organization: Mapped[str] = mapped_column(String(300), default='')
    role: Mapped[str] = mapped_column(String(300), default='')
    information: Mapped[str] = mapped_column(Text, default='')
    met_at: Mapped[str] = mapped_column(Text, default='')
    notes: Mapped[str] = mapped_column(Text, default='')
    followup_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default='New')
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey('opportunities.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Earning(Base):
    __tablename__ = 'earnings'
    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey('opportunities.id'), nullable=True)
    date: Mapped[datetime] = mapped_column(DateTime)
    gross: Mapped[float] = mapped_column(Float)
    expenses: Mapped[float] = mapped_column(Float)
    hours: Mapped[float] = mapped_column(Float)
    notes: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ResearchRun(Base):
    __tablename__ = 'research_runs'
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default='Running')
    discovered: Mapped[int] = mapped_column(Integer, default=0)
    accepted: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    filtered: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[str] = mapped_column(Text, default='')
