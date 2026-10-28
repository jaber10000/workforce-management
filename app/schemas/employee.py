from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field

from app.models.employee import Gender, RolePool, Weekday


class EmployeeBase(BaseModel):
    employee_id: str = Field(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9_-]+$")
    full_name: str = Field(min_length=1, max_length=150)
    gender: Gender | None = None
    phone_number: str | None = Field(default=None, max_length=40)
    home_thana: str | None = Field(default=None, max_length=100)
    role_pool: RolePool = RolePool.general
    weekly_off_day: Weekday | None = None
    half_duty_day: Weekday | None = None
    joining_date: date | None = None
    is_shift_eligible_morning: bool = True
    is_shift_eligible_evening: bool = True
    is_shift_eligible_night: bool = False
    is_active: bool = True
    notes: str | None = Field(default=None, max_length=500)
    team: str | None = Field(default=None, max_length=40)


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    gender: Gender | None = None
    phone_number: str | None = Field(default=None, max_length=40)
    home_thana: str | None = Field(default=None, max_length=100)
    role_pool: RolePool | None = None
    weekly_off_day: Weekday | None = None
    half_duty_day: Weekday | None = None
    joining_date: date | None = None
    is_shift_eligible_morning: bool | None = None
    is_shift_eligible_evening: bool | None = None
    is_shift_eligible_night: bool | None = None
    is_active: bool | None = None
    notes: str | None = Field(default=None, max_length=500)
    team: str | None = Field(default=None, max_length=40)


class EmployeeRead(EmployeeBase):
    id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class EmployeePage(BaseModel):
    items: list[EmployeeRead]
    total: int
    skip: int
    limit: int


class ImportResult(BaseModel):
    created: int
    updated: int
    skipped: int
    errors: list[str]
