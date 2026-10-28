from datetime import date, datetime

from sqlalchemy import (JSON, Date, DateTime, Float, ForeignKey, Index, Integer, String,
                        UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class DailyRequirement(Base):
    __tablename__ = "daily_requirements"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    morning_required: Mapped[int] = mapped_column(Integer)
    evening_required: Mapped[int] = mapped_column(Integer)
    night_required: Mapped[int] = mapped_column(Integer)
    min_senior: Mapped[int] = mapped_column(Integer)


class RosterVersion(Base):
    """One immutable snapshot of a roster. Regeneration always creates a new row."""

    __tablename__ = "roster_versions"
    __table_args__ = (UniqueConstraint("roster_key", "version_no", name="uq_roster_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    roster_key: Mapped[str] = mapped_column(String(30), index=True)  # "<start>_<end>"
    version_no: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)  # draft | approved | rejected | published | superseded
    trigger: Mapped[str] = mapped_column(String(40), default="manual")
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    base_version_id: Mapped[int | None] = mapped_column(ForeignKey("roster_versions.id"), nullable=True)
    lock_before: Mapped[date | None] = mapped_column(Date, nullable=True)
    solver_status: Mapped[str] = mapped_column(String(30), default="")
    objective: Mapped[float | None] = mapped_column(Float, nullable=True)
    solve_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    published_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RosterAssignment(Base):
    __tablename__ = "roster_assignments"
    __table_args__ = (
        UniqueConstraint("version_id", "employee_id", "work_date", name="uq_assignment_cell"),
        Index("ix_assignment_version_employee", "version_id", "employee_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("roster_versions.id", ondelete="CASCADE"), index=True)
    employee_id: Mapped[str] = mapped_column(String(30))
    work_date: Mapped[date] = mapped_column(Date)
    code: Mapped[str] = mapped_column(String(8))  # M E N M-H E-H N-H R WO SL CL AL -
    weight: Mapped[float] = mapped_column(Float, default=0.0)  # coverage weight: 1, 0.5 or 0


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    actor: Mapped[str] = mapped_column(String(100), default="system")
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(60))
    version_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class SwapRequest(Base):
    """Two employees exchange their shifts on one date. Needs the counterpart's consent and a manager's approval."""

    __tablename__ = "swap_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    swap_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    requester_id: Mapped[str] = mapped_column(String(30), index=True)
    counterpart_id: Mapped[str] = mapped_column(String(30), index=True)
    work_date: Mapped[date] = mapped_column(Date, index=True)
    # pending_counterpart -> pending_manager -> approved | rejected ; also declined / cancelled
    status: Mapped[str] = mapped_column(String(24), default="pending_counterpart", index=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    result_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
