from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RequirementIn(BaseModel):
    work_date: date
    morning_required: int = Field(ge=0, le=2000)
    evening_required: int = Field(ge=0, le=2000)
    night_required: int = Field(ge=0, le=2000)
    min_senior: int = Field(default=3, ge=0, le=2000)


class RequirementRead(RequirementIn):
    model_config = ConfigDict(from_attributes=True)


class GenerateIn(BaseModel):
    start_date: date
    end_date: date | None = None
    days: int = Field(default=14, ge=1, le=62)
    time_limit_seconds: float = Field(default=30.0, ge=1, le=300)
    reason: str | None = Field(default=None, max_length=500)
    requirements: list[RequirementIn] | None = None

    @model_validator(mode="after")
    def _fill_end(self):
        if self.end_date is None:
            from datetime import timedelta
            self.end_date = self.start_date + timedelta(days=self.days - 1)
        return self


class RegenerateIn(BaseModel):
    base_version_id: int
    from_date: date | None = None
    time_limit_seconds: float = Field(default=30.0, ge=1, le=300)
    reason: str | None = Field(default=None, max_length=500)


class PublishIn(BaseModel):
    acknowledge_shortage: bool = False
    decided_by: str | None = Field(default=None, max_length=100)  # honoured only when auth is disabled


class ApproveIn(PublishIn):
    note: str | None = Field(default=None, max_length=500)


class RejectIn(BaseModel):
    note: str = Field(min_length=3, max_length=500)
    decided_by: str | None = Field(default=None, max_length=100)


class CellEdit(BaseModel):
    employee_id: str
    work_date: date
    code: str
    reason: str = Field(min_length=3, max_length=500)


class VersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    roster_key: str
    version_no: int
    start_date: date
    end_date: date
    status: str
    trigger: str
    reason: str | None
    base_version_id: int | None
    lock_before: date | None
    solver_status: str
    objective: float | None
    solve_seconds: float
    summary: dict[str, Any]
    created_at: datetime
    created_by: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    review_note: str | None = None
    published_by: str | None = None
    published_at: datetime | None


class AuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    actor: str
    action: str
    entity_type: str
    entity_id: str
    version_id: int | None
    details: dict[str, Any]
