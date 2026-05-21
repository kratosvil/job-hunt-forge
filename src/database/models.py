from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import String, Float, Text, Boolean, DateTime, Integer, Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class JobStatus(str, Enum):
    PENDING = "pending"
    ANALYZED = "analyzed"
    SKIPPED = "skipped"
    APPLIED = "applied"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    OFFER = "offer"


class ManagerStatus(str, Enum):
    PENDING = "pending"
    MESSAGE_QUEUED = "message_queued"
    MESSAGE_SENT = "message_sent"
    REPLIED = "replied"
    NOT_FOUND = "not_found"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    company: Mapped[str] = mapped_column(String(256), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(256))
    jd_text: Mapped[Optional[str]] = mapped_column(Text)
    fit_score: Mapped[Optional[float]] = mapped_column(Float)
    matched_skills: Mapped[Optional[str]] = mapped_column(Text)   # JSON array
    missing_skills: Mapped[Optional[str]] = mapped_column(Text)   # JSON array
    salary_range: Mapped[Optional[str]] = mapped_column(String(128))
    remote_friendly: Mapped[Optional[bool]] = mapped_column(Boolean)
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus), default=JobStatus.PENDING, nullable=False
    )
    source: Mapped[Optional[str]] = mapped_column(String(64))     # linkedin | indeed
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)


class HiringManager(Base):
    __tablename__ = "hiring_managers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[Optional[str]] = mapped_column(String(256))
    company: Mapped[str] = mapped_column(String(256), nullable=False)
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(2048), unique=True)
    contact_url: Mapped[Optional[str]] = mapped_column(String(2048))
    message_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    message_text: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[ManagerStatus] = mapped_column(
        SAEnum(ManagerStatus), default=ManagerStatus.PENDING, nullable=False
    )
    job_id: Mapped[Optional[int]] = mapped_column(Integer)        # FK to jobs.id
    found_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    contacted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
