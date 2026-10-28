from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LeaveTypeLit = Literal["Sick", "Casual", "Annual"]
LeaveStatusLit = Literal["Pending", "Approved", "Rejected", "Cancelled"]


class LeaveCreate(BaseModel):
    employee_id: str = Field(min_length=1, max_length=30)
    leave_type: LeaveTypeLit
    start_date: date
    end_date: date
    half_day: bool = False
    reason: str | None = Field(default=None, max_length=500)


class LeaveDecision(BaseModel):
    note: str | None = Field(default=None, max_length=500)
    decided_by: str = Field(default="system", max_length=100)
    auto_roster: bool = True


class LeaveRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: str
    employee_id: str
    leave_type: str
    start_date: date
    end_date: date
    half_day: bool
    days: float
    status: str
    reason: str | None
    decided_by: str | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime


class LeavePage(BaseModel):
    items: list[LeaveRead]
    total: int
    skip: int
    limit: int


class LeaveBalanceRead(BaseModel):
    leave_type: str
    year: int
    entitlement: float
    carried_forward: float
    total: float
    used: float
    pending: float
    remaining: float
    available: float
    half_day_allowed: bool
