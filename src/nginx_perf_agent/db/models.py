"""SQLAlchemy ORM models."""

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class EmailRecord(Base):
    """A monitoring email that matched the subject filter."""

    __tablename__ = "emails"
    __table_args__ = (UniqueConstraint("mailbox", "uid", name="uq_emails_mailbox_uid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    mailbox: Mapped[str] = mapped_column(String(255))
    uid: Mapped[str] = mapped_column(String(64))
    subject: Mapped[str] = mapped_column(String(512))
    sender: Mapped[str | None] = mapped_column(String(512))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    attachments: Mapped[list["Attachment"]] = relationship(back_populates="email")


class Attachment(Base):
    """An attachment extracted from an email. `sha256` is the dedup key."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    email_id: Mapped[int] = mapped_column(ForeignKey("emails.id"), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    stored_path: Mapped[str] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    email: Mapped[EmailRecord] = relationship(back_populates="attachments")


class AnalysisTask(Base):
    """A log-analysis job and its outcome."""

    __tablename__ = "analysis_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    attachment_id: Mapped[int | None] = mapped_column(
        ForeignKey("attachments.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    report_path: Mapped[str | None] = mapped_column(String(1024))
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
