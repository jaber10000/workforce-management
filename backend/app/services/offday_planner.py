"""New weekly-off / half-duty day after a long continuous leave.

Rule: when an employee has more than LONG_LEAVE_REPLAN_DAYS continuous approved leave days,
the first roster week after the leave gets a NEW weekly-off day (and half-duty day if the person
has one), picked so the employee's pool (same role pool + night eligibility) keeps even weekly-off
coverage. Earlier rosters are untouched; the plan is effective-dated."""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.leave_policy import LONG_LEAVE_REPLAN_DAYS, ROSTER_WEEK_START
from app.models.employee import Employee
from app.models.leave import LeaveApplication, OffDayPlan
from app.services import audit

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def continuous_run(db: Session, lv: LeaveApplication) -> tuple[date, date]:
    """Whole-day approved leave of this employee that touches/overlaps ``lv`` (adjacent days chain)."""
    rows = db.scalars(select(LeaveApplication).where(
        LeaveApplication.employee_id == lv.employee_id, LeaveApplication.half_day.is_(False),
        LeaveApplication.status == "Approved")).all()
    spans = sorted({(r.start_date, r.end_date) for r in rows} | {(lv.start_date, lv.end_date)})
    run_start, run_end = lv.start_date, lv.end_date
    changed = True
    while changed:
        changed = False
        for s, e in spans:
            if s <= run_end + timedelta(days=1) and e >= run_start - timedelta(days=1) and (s < run_start or e > run_end):
                run_start, run_end, changed = min(run_start, s), max(run_end, e), True
    return run_start, run_end


def next_week_start(after: date) -> date:
    d = after + timedelta(days=1)
    while d.weekday() != ROSTER_WEEK_START:
        d += timedelta(days=1)
    return d


def _current(emp: Employee, plans: list[OffDayPlan], on: date) -> tuple[int | None, int | None]:
    off = WEEKDAYS.index(emp.weekly_off_day.value) if emp.weekly_off_day else None
    half = WEEKDAYS.index(emp.half_duty_day.value) if emp.half_duty_day else None
    for p in plans:
        if p.effective_from <= on:
            off, half = p.weekly_off, p.half_duty
    return off, half


def choose_days(db: Session, emp: Employee, effective_from: date) -> tuple[int, int | None]:
    plans: dict[str, list[OffDayPlan]] = {}
    for p in db.scalars(select(OffDayPlan).order_by(OffDayPlan.effective_from, OffDayPlan.id)):
        plans.setdefault(p.employee_id, []).append(p)
    off_load, half_load = Counter(), Counter()
    for o in db.scalars(select(Employee).where(Employee.is_active.is_(True), Employee.employee_id != emp.employee_id)):
        if o.role_pool != emp.role_pool or bool(o.is_shift_eligible_night) != bool(emp.is_shift_eligible_night):
            continue
        wo, hd = _current(o, plans.get(o.employee_id, []), effective_from)
        if wo is not None: off_load[wo] += 1
        if hd is not None: half_load[hd] += 1
    old_off, old_half = _current(emp, plans.get(emp.employee_id, []), effective_from)
    order = [(ROSTER_WEEK_START + i) % 7 for i in range(7)]
    cands = [d for d in order if d != old_off] or order
    new_off = min(cands, key=lambda d: (off_load[d], order.index(d)))
    new_half = None
    if old_half is not None:
        hc = [d for d in order if d != new_off]
        new_half = min(hc, key=lambda d: (half_load[d], d != old_half, order.index(d)))
    return new_off, new_half


def replan_after_long_leave(db: Session, lv: LeaveApplication, actor: str) -> dict | None:
    if lv.half_day:
        return None
    run_start, run_end = continuous_run(db, lv)
    run_days = (run_end - run_start).days + 1
    if run_days <= LONG_LEAVE_REPLAN_DAYS:
        return None
    emp = db.scalar(select(Employee).where(Employee.employee_id == lv.employee_id))
    if emp is None:
        return None
    eff = next_week_start(run_end)
    existing = db.scalar(select(OffDayPlan).where(OffDayPlan.employee_id == emp.employee_id,
                                                  OffDayPlan.effective_from == eff))
    off, half = choose_days(db, emp, eff)
    reason = f"{run_days} continuous leave days ({run_start}..{run_end}) via {lv.application_id}"
    if existing:
        existing.weekly_off, existing.half_duty, existing.source_application_id, existing.reason = (
            off, half, lv.application_id, reason)
    else:
        db.add(OffDayPlan(employee_id=emp.employee_id, effective_from=eff, weekly_off=off, half_duty=half,
                          source_application_id=lv.application_id, reason=reason))
    db.flush()
    info = {"employee_id": emp.employee_id, "effective_from": eff.isoformat(), "continuous_days": run_days,
            "weekly_off": WEEKDAYS[off], "half_duty": WEEKDAYS[half] if half is not None else None,
            "previous_weekly_off": emp.weekly_off_day.value if emp.weekly_off_day else None}
    audit.log(db, "off_day_replanned", "employee", emp.employee_id, {**info, "application_id": lv.application_id},
              actor=actor)
    return info


def remove_plans(db: Session, lv: LeaveApplication, today: date, actor: str) -> int:
    """Leave cancelled: drop its not-yet-effective plan(s). Plans already in force are history and stay."""
    rows = db.scalars(select(OffDayPlan).where(OffDayPlan.source_application_id == lv.application_id,
                                               OffDayPlan.effective_from > today)).all()
    for r in rows:
        audit.log(db, "off_day_plan_removed", "employee", r.employee_id,
                  {"application_id": lv.application_id, "effective_from": r.effective_from.isoformat()}, actor=actor)
        db.delete(r)
    db.flush()
    return len(rows)
