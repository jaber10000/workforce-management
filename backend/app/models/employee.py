import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Gender(str, enum.Enum):
    female = "female"
    male = "male"
    other = "other"
    prefer_not_to_say = "prefer_not_to_say"


class RolePool(str, enum.Enum):
    general = "general"
    senior_support = "senior_support"
    supervisor = "supervisor"
    other = "other"


class Weekday(str, enum.Enum):
    monday = "Monday"
    tuesday = "Tuesday"
    wednesday = "Wednesday"
    thursday = "Thursday"
    friday = "Friday"
    saturday = "Saturday"
    sunday = "Sunday"


WEEKDAY_ENUM = Enum(Weekday, name="weekday")


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    employee_id: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150), index=True)
    gender: Mapped[Gender | None] = mapped_column(Enum(Gender, name="employee_gender"), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    home_thana: Mapped[str | None] = mapped_column(String(100), nullable=True)
    role_pool: Mapped[RolePool] = mapped_column(
        Enum(RolePool, name="employee_role_pool"), default=RolePool.general, nullable=False
    )
    weekly_off_day: Mapped[Weekday | None] = mapped_column(WEEKDAY_ENUM, nullable=True)
    half_duty_day: Mapped[Weekday | None] = mapped_column(WEEKDAY_ENUM, nullable=True)
    joining_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_shift_eligible_morning: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_shift_eligible_evening: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_shift_eligible_night: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    team: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)  # named after the leader, e.g. 'Team Arif'
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
