from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

ROLES = ("admin", "manager", "supervisor", "employee")


class AppUser(Base):
    """Login account. role: admin (everything + users) | manager (roster, leave, swaps, audit, Excel import) |
    supervisor (review rosters/leave/swaps, edit drafts; no approve/publish, no private employee data) |
    employee (own leave, own swaps, published roster)."""

    __tablename__ = "app_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="employee")
    employee_id: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
