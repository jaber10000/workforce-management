from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class TeamMessage(Base):
    """One message in the private conversation between an employee and their team leader (thread = employee_id).
    side: 'employee' (written by the employee) | 'staff' (team leader / manager). An optional image is stored with it."""

    __tablename__ = "team_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(30), index=True)  # whose thread
    sender: Mapped[str] = mapped_column(String(60))
    sender_name: Mapped[str] = mapped_column(String(150))
    side: Mapped[str] = mapped_column(String(10))
    topic: Mapped[str | None] = mapped_column(String(80), nullable=True)
    body: Mapped[str] = mapped_column(Text, default="")
    image_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    image_mime: Mapped[str | None] = mapped_column(String(40), nullable=True)
    image_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    image_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    read_by_employee: Mapped[bool] = mapped_column(Boolean, default=False)
    read_by_staff: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
