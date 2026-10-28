from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class LeaveApplication(Base):
    __tablename__ = "leave_applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    employee_id: Mapped[str] = mapped_column(String(30), index=True)
    leave_type: Mapped[str] = mapped_column(String(20))  # Sick | Casual | Annual
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date] = mapped_column(Date)
    half_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    days: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="Pending", index=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LeaveBalance(Base):
    """Per employee / year / type entitlement row (created lazily from the policy)."""

    __tablename__ = "leave_balances"
    __table_args__ = (UniqueConstraint("employee_id", "year", "leave_type", name="uq_leave_balance"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(30), index=True)
    year: Mapped[int] = mapped_column(Integer)
    leave_type: Mapped[str] = mapped_column(String(20))
    entitlement: Mapped[float] = mapped_column(Float)
    carried_forward: Mapped[float] = mapped_column(Float, default=0.0)


class OffDayPlan(Base):
    """Effective-dated weekly-off / half-duty weekday (Monday=0). The latest plan whose
    ``effective_from`` <= the date wins over Employee.weekly_off_day / half_duty_day.
    Created when a long leave ends; history before ``effective_from`` is never touched."""

    __tablename__ = "off_day_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(30), index=True)
    effective_from: Mapped[date] = mapped_column(Date, index=True)
    weekly_off: Mapped[int | None] = mapped_column(Integer, nullable=True)
    half_duty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_application_id: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
