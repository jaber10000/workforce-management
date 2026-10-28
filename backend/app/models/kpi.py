from datetime import datetime

from sqlalchemy import DateTime, Float, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class EmployeeKpi(Base):
    """One employee's KPI for one calendar month (period = 'YYYY-MM'), uploaded by their supervisor or senior agent.
    All metrics are percentages 0-100. `score` is the overall result: given explicitly or the mean of the metrics."""

    __tablename__ = "employee_kpis"
    __table_args__ = (UniqueConstraint("employee_id", "period", name="uq_kpi_employee_period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(30), index=True)
    period: Mapped[str] = mapped_column(String(7), index=True)
    score: Mapped[float] = mapped_column(Float)
    quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    attendance: Mapped[float | None] = mapped_column(Float, nullable=True)
    productivity: Mapped[float | None] = mapped_column(Float, nullable=True)
    csat: Mapped[float | None] = mapped_column(Float, nullable=True)
    remarks: Mapped[str | None] = mapped_column(String(500), nullable=True)
    uploaded_by: Mapped[str] = mapped_column(String(60))
    uploaded_by_name: Mapped[str] = mapped_column(String(150))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
