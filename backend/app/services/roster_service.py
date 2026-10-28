"""Roster orchestration: build engine input from the DB, persist immutable versions,
coverage validation, fairness report, published-roster protection and auto-adjustment."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.employee import Employee, RolePool
from app.models.leave import LeaveApplication, OffDayPlan
from app.models.roster import DailyRequirement, RosterAssignment, RosterVersion
from app.services import audit
from app.services.roster_engine import (EmpIn, EngineError, EngineInput, LeaveIn, ReqIn,
                                        code_shift, code_weight, solve)

log = logging.getLogger(__name__)

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
VALID_CODES = {"M", "E", "N", "M-H", "E-H", "N-H", "R", "WO", "SL", "CL", "AL", "-"}
MAX_DAYS = 62


class RosterError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


# ------------------------------------------------------------ requirements --

def default_requirement() -> ReqIn:
    return ReqIn(settings.default_morning_required, settings.default_evening_required,
                 settings.default_night_required, settings.default_min_senior)


def load_requirements(db: Session, start: date, end: date) -> dict[date, ReqIn]:
    rows = {r.work_date: r for r in db.scalars(select(DailyRequirement).where(
        DailyRequirement.work_date >= start, DailyRequirement.work_date <= end))}
    default = default_requirement()
    out = {}
    for d in _daterange(start, end):
        r = rows.get(d)
        out[d] = ReqIn(r.morning_required, r.evening_required, r.night_required, r.min_senior) if r else default
    return out


def upsert_requirements(db: Session, items: list[dict]) -> int:
    for it in items:
        row = db.scalar(select(DailyRequirement).where(DailyRequirement.work_date == it["work_date"]))
        if row is None:
            row = DailyRequirement(work_date=it["work_date"])
            db.add(row)
        row.morning_required = it["morning_required"]
        row.evening_required = it["evening_required"]
        row.night_required = it["night_required"]
        row.min_senior = it["min_senior"]
    db.flush()
    return len(items)


# --------------------------------------------------------------- versions --

def get_version(db: Session, version_id: int) -> RosterVersion:
    v = db.get(RosterVersion, version_id)
    if not v:
        raise RosterError("Roster version not found", 404)
    return v


def version_assignments(db: Session, version_id: int) -> dict[tuple[str, date], str]:
    rows = db.execute(select(RosterAssignment.employee_id, RosterAssignment.work_date, RosterAssignment.code)
                      .where(RosterAssignment.version_id == version_id))
    return {(e, d): c for e, d, c in rows}


def latest_version(db: Session, start: date, end: date) -> RosterVersion | None:
    return db.scalar(select(RosterVersion).where(
        RosterVersion.start_date <= end, RosterVersion.end_date >= start,
        RosterVersion.status.in_(("draft", "approved", "published")),
    ).order_by(RosterVersion.id.desc()).limit(1))


def _employee_in(e: Employee, plans: tuple = ()) -> EmpIn:
    return EmpIn(
        plans=plans, emp_id=e.employee_id, senior=e.role_pool == RolePool.senior_support,
        morning=e.is_shift_eligible_morning, evening=e.is_shift_eligible_evening,
        night=e.is_shift_eligible_night,
        weekly_off=WEEKDAYS.index(e.weekly_off_day.value) if e.weekly_off_day else None,
        half_duty=WEEKDAYS.index(e.half_duty_day.value) if e.half_duty_day else None,
        joining=e.joining_date, active=e.is_active)


def load_off_plans(db: Session, emp_ids) -> dict[str, tuple]:
    out: dict[str, list] = defaultdict(list)
    for p in db.scalars(select(OffDayPlan).where(OffDayPlan.employee_id.in_(list(emp_ids)))
                        .order_by(OffDayPlan.effective_from, OffDayPlan.id)):
        out[p.employee_id].append((p.effective_from, p.weekly_off, p.half_duty))
    return {k: tuple(v) for k, v in out.items()}


def _history(db: Session, start: date, employee_ids: set[str]) -> dict[tuple[str, date], str]:
    """Last days of the roster that ends right before ``start`` (rest-rule continuity)."""
    prev = db.scalar(select(RosterVersion).where(RosterVersion.end_date == start - timedelta(days=1))
                     .order_by(RosterVersion.id.desc()).limit(1))
    if not prev:
        return {}
    since = start - timedelta(days=7)
    rows = db.execute(select(RosterAssignment.employee_id, RosterAssignment.work_date, RosterAssignment.code)
                      .where(RosterAssignment.version_id == prev.id, RosterAssignment.work_date >= since))
    return {(e, d): c for e, d, c in rows if e in employee_ids}


def _build_version(db: Session, *, start: date, end: date, base: RosterVersion | None,
                   lock_before: date | None, trigger: str, reason: str | None, time_limit: float,
                   actor: str, extra_audit: dict | None = None) -> RosterVersion:
    if end < start:
        raise RosterError("end_date cannot be before start_date", 422)
    if (end - start).days + 1 > MAX_DAYS:
        raise RosterError(f"Roster window is limited to {MAX_DAYS} days", 422)

    base_codes = version_assignments(db, base.id) if base else {}
    base_emp_ids = {e for (e, _) in base_codes}
    stmt = select(Employee).order_by(Employee.employee_id)
    employees = [e for e in db.scalars(stmt) if e.is_active or e.employee_id in base_emp_ids]
    if not employees:
        raise RosterError("No active employees to roster", 409)
    emp_ids = {e.employee_id for e in employees}

    leaves = db.scalars(select(LeaveApplication).where(
        LeaveApplication.start_date <= end, LeaveApplication.end_date >= start,
        LeaveApplication.employee_id.in_(emp_ids))).all()
    approved = [LeaveIn(l.employee_id, l.start_date, l.end_date, l.leave_type, l.half_day)
                for l in leaves if l.status == "Approved"]
    pending = [l for l in leaves if l.status == "Pending"]

    free_from = max(lock_before or start, start)
    frozen = {k: c for k, c in base_codes.items() if k[1] < free_from}
    free_base = {k: c for k, c in base_codes.items() if k[1] >= free_from}
    requirements = load_requirements(db, start, end)
    plans = load_off_plans(db, emp_ids)

    engine_in = EngineInput(
        start=start, end=end, employees=[_employee_in(e, plans.get(e.employee_id, ())) for e in employees], leaves=approved,
        requirements=requirements, free_from=free_from, frozen=frozen,
        history=_history(db, start, emp_ids), base=free_base, time_limit=time_limit,
        workers=settings.solver_workers)
    try:
        result = solve(engine_in)
    except EngineError as exc:
        raise RosterError(str(exc), 409) from exc

    key = f"{start.isoformat()}_{end.isoformat()}"
    version_no = (db.scalar(select(func.max(RosterVersion.version_no)).where(RosterVersion.roster_key == key)) or 0) + 1
    version = RosterVersion(
        roster_key=key, version_no=version_no, start_date=start, end_date=end, status="draft",
        trigger=trigger, reason=reason, base_version_id=base.id if base else None, created_by=actor,
        lock_before=free_from if base else None, solver_status=result.status,
        objective=result.objective, solve_seconds=round(result.seconds, 2), summary={})
    db.add(version)
    db.flush()

    db.bulk_insert_mappings(RosterAssignment, [
        {"version_id": version.id, "employee_id": emp, "work_date": d, "code": code,
         "weight": code_weight(code)} for (emp, d), code in result.codes.items()])
    db.flush()

    cov = coverage_report(db, version.id, employees=employees)
    changes = diff_codes(base_codes, result.codes) if base else []
    summary = {
        "employees": len(employees),
        "shortage": cov["totals"],
        "days_with_shortage": cov["days_with_shortage"],
        "changes": len(changes),
        "pending_leaves_not_applied": len(pending),
        "warnings": [],
    }
    if pending:
        summary["warnings"].append(
            f"{len(pending)} pending leave application(s) are not applied until approved")
    if cov["days_with_shortage"]:
        summary["warnings"].append(f"Shortage on {cov['days_with_shortage']} day(s) - see coverage report")
    if base and base.status == "published":
        summary["warnings"].append(f"Published history before {free_from} was kept unchanged")
    version.summary = summary
    audit.log(db, "roster_generated" if not base else "roster_regenerated", "roster_version", version.id,
              {"roster_key": key, "version_no": version_no, "trigger": trigger, "reason": reason,
               "base_version_id": base.id if base else None, "lock_before": str(free_from) if base else None,
               "solver_status": result.status, "shortage": cov["totals"], "changes": len(changes),
               **(extra_audit or {})}, version_id=version.id, actor=actor)
    return version


def generate_roster(db: Session, *, start_date: date, end_date: date, requirements: list[dict] | None = None,
                    time_limit: float | None = None, reason: str | None = None, actor: str = "system",
                    trigger: str = "manual") -> RosterVersion:
    """Build a brand-new draft roster (new version of the same window when one already exists)."""
    if requirements:
        upsert_requirements(db, requirements)
    key = f"{start_date.isoformat()}_{end_date.isoformat()}"
    existing = db.scalar(select(func.count()).select_from(RosterVersion).where(RosterVersion.roster_key == key))
    version = _build_version(
        db, start=start_date, end=end_date, base=None, lock_before=None,
        trigger=trigger if not existing else "manual_regenerate", reason=reason,
        time_limit=time_limit or settings.solver_time_limit_seconds, actor=actor)
    db.commit()
    db.refresh(version)
    return version


def regenerate_roster(db: Session, *, base_version_id: int, from_date: date | None = None,
                      reason: str | None = None, time_limit: float | None = None, today: date | None = None,
                      actor: str = "system", trigger: str = "manual_reoptimize", commit: bool = True) -> RosterVersion:
    """Re-optimise a roster from ``from_date`` onward as a NEW version.

    Days before ``from_date`` are copied unchanged. When the base is published, days before today
    are always locked too, so published history can never change."""
    base = get_version(db, base_version_id)
    if base.status in ("published", "approved") and trigger == "manual_reoptimize" and len((reason or "").strip()) < 3:
        raise RosterError("A change reason is required to re-optimise an approved or published roster", 422)
    today = today or date.today()
    lock_before = max(from_date or base.start_date, base.start_date)
    if base.status == "published":
        lock_before = max(lock_before, today)
    if lock_before > base.end_date:
        raise RosterError("Nothing to re-optimise: the requested period is already in the past or locked", 409)
    version = _build_version(
        db, start=base.start_date, end=base.end_date, base=base, lock_before=lock_before,
        trigger=trigger, reason=reason, time_limit=time_limit or settings.solver_time_limit_seconds, actor=actor)
    if commit:
        db.commit()
        db.refresh(version)
    return version


def auto_adjust(db: Session, *, trigger: str, from_date: date, to_date: date | None = None,
                reason: str, today: date | None = None, actor: str = "system",
                time_limit: float | None = None, commit: bool = True) -> RosterVersion | None:
    """Leave approved/cancelled, employee added/deactivated -> new roster version with minimal changes.

    Returns None when no roster covers the affected period (nothing to adjust)."""
    to_date = to_date or from_date
    base = latest_version(db, from_date, to_date)
    if base is None:
        return None
    today = today or date.today()
    lock = max(from_date, base.start_date)
    if base.status == "published":
        lock = max(lock, today)
    if lock > base.end_date or lock > to_date:
        audit.log(db, "roster_adjust_skipped", "roster_version", base.id,
                  {"trigger": trigger, "reason": reason, "why": "affected period is in the past / locked published history"},
                  version_id=base.id, actor=actor)
        if commit:
            db.commit()
        return None
    # An affected day that is already published history cannot be changed: start from today.
    version = _build_version(
        db, start=base.start_date, end=base.end_date, base=base, lock_before=lock, trigger=trigger,
        reason=reason, time_limit=time_limit or settings.auto_adjust_time_limit_seconds, actor=actor)
    if commit:
        db.commit()
        db.refresh(version)
    return version


def _now():
    return datetime.now(timezone.utc)


def _shortage_total(v: RosterVersion) -> float:
    return (v.summary or {}).get("shortage", {}).get("total", 0)


def approve(db: Session, version_id: int, *, acknowledge_shortage: bool = False, note: str | None = None,
            actor: str = "system") -> RosterVersion:
    """Manager review: a draft becomes 'approved' (locked, ready to publish)."""
    v = get_version(db, version_id)
    if v.status != "draft":
        raise RosterError(f"Only a draft can be approved (current: {v.status})", 409)
    short = _shortage_total(v)
    if short and not acknowledge_shortage:
        raise RosterError(
            f"This roster has shortage ({short:g} person-shifts). Pass acknowledge_shortage=true to approve anyway", 409)
    warns = [w for w in version_warnings(db, version_id) if w["severity"] == "danger"]
    if warns and not acknowledge_shortage:
        raise RosterError("Resolve or acknowledge these problems first: " + "; ".join(w["message"] for w in warns), 409)
    v.status, v.approved_by, v.approved_at, v.review_note = "approved", actor, _now(), note
    audit.log(db, "roster_approved", "roster_version", v.id,
              {"roster_key": v.roster_key, "version_no": v.version_no, "shortage": short, "note": note,
               "warnings": [w["type"] for w in warns],
               "acknowledged_shortage": bool(short)}, version_id=v.id, actor=actor)
    db.commit()
    db.refresh(v)
    return v


def reject(db: Session, version_id: int, *, note: str, actor: str = "system") -> RosterVersion:
    """Manager sends a draft/approved version back. It is kept (audit) but can no longer be published."""
    v = get_version(db, version_id)
    if v.status not in ("draft", "approved"):
        raise RosterError(f"Only a draft or approved version can be rejected (current: {v.status})", 409)
    v.status, v.review_note = "rejected", note
    audit.log(db, "roster_rejected", "roster_version", v.id,
              {"roster_key": v.roster_key, "version_no": v.version_no, "note": note}, version_id=v.id, actor=actor)
    db.commit()
    db.refresh(v)
    return v


def publish(db: Session, version_id: int, *, acknowledge_shortage: bool = False, actor: str = "system") -> RosterVersion:
    v = get_version(db, version_id)
    if v.status == "published":
        raise RosterError("This version is already published", 409)
    if v.status in ("rejected", "superseded"):
        raise RosterError(f"A {v.status} version cannot be published", 409)
    if settings.require_approval and v.status != "approved":
        raise RosterError("Approve the draft first (manager review), then publish", 409)
    if settings.require_approval and settings.separate_approver and v.approved_by == actor:
        raise RosterError("Four-eyes rule: the publisher must be a different person than the approver", 403)
    shortage = _shortage_total(v)
    if shortage and not acknowledge_shortage:
        raise RosterError(
            f"This roster has shortage ({shortage:g} person-shifts). Pass acknowledge_shortage=true to publish anyway", 409)
    for old in db.scalars(select(RosterVersion).where(
            RosterVersion.roster_key == v.roster_key, RosterVersion.status == "published", RosterVersion.id != v.id)):
        old.status = "superseded"
    v.status, v.published_at, v.published_by = "published", _now(), actor
    audit.log(db, "roster_published", "roster_version", v.id,
              {"roster_key": v.roster_key, "version_no": v.version_no, "shortage": shortage,
               "approved_by": v.approved_by}, version_id=v.id, actor=actor)
    db.commit()
    db.refresh(v)
    return v


def _cell_conflicts(db: Session, version_id: int, emp: Employee, d: date, code: str) -> str | None:
    """Hard rules for a manual edit: eligibility and Night->Morning. Returns a message or None."""
    shift = code_shift(code)
    if shift is None:
        return None
    flag = {"M": emp.is_shift_eligible_morning, "E": emp.is_shift_eligible_evening, "N": emp.is_shift_eligible_night}[shift]
    if not flag:
        return f"{emp.employee_id} is not eligible for the {shift} shift"
    def code_on(day):
        return db.scalar(select(RosterAssignment.code).where(
            RosterAssignment.version_id == version_id, RosterAssignment.employee_id == emp.employee_id,
            RosterAssignment.work_date == day)) or ""
    if shift == "M" and code_shift(code_on(d - timedelta(days=1))) == "N":
        return "Night followed by Morning is not allowed"
    if shift == "N" and code_shift(code_on(d + timedelta(days=1))) == "M":
        return "Night followed by Morning is not allowed"
    return None


def edit_cell(db: Session, version_id: int, employee_id: str, work_date: date, code: str,
              actor: str = "system", reason: str | None = None) -> RosterAssignment:
    """Manual override. Drafts only; every change keeps who / when / old value / new value / reason."""
    v = get_version(db, version_id)
    if v.status != "draft":
        raise RosterError(f"Only drafts can be edited ({v.status} rosters are locked). "
                          "Re-optimise to create a new draft version", 409)
    if len((reason or "").strip()) < 3:
        raise RosterError("A change reason is required (min 3 characters)", 422)
    if code not in VALID_CODES:
        raise RosterError(f"Invalid code '{code}'", 422)
    if v.lock_before and work_date < v.lock_before:
        raise RosterError(f"Dates before {v.lock_before} are locked history", 409)
    row = db.scalar(select(RosterAssignment).where(
        RosterAssignment.version_id == version_id, RosterAssignment.employee_id == employee_id,
        RosterAssignment.work_date == work_date))
    if not row:
        raise RosterError("Assignment not found", 404)
    old = row.code
    if old in ("SL", "CL", "AL"):
        raise RosterError("This cell is approved leave. Cancel the leave application instead of editing the roster", 409)
    if code in ("SL", "CL", "AL"):
        raise RosterError("Leave codes come only from approved leave applications", 422)
    emp = db.scalar(select(Employee).where(Employee.employee_id == employee_id))
    if emp is not None:
        problem = _cell_conflicts(db, version_id, emp, work_date, code)
        if problem:
            raise RosterError(problem, 409)
    row.code = code
    row.weight = code_weight(code)
    db.flush()
    cov = coverage_report(db, version_id)
    v.summary = {**(v.summary or {}), "shortage": cov["totals"], "days_with_shortage": cov["days_with_shortage"]}
    audit.log(db, "roster_cell_edited", "roster_version", version_id,
              {"employee_id": employee_id, "employee_name": emp.full_name if emp else None, "date": str(work_date),
               "from": old, "to": code, "reason": reason.strip()},
              version_id=version_id, actor=actor)
    db.commit()
    return row


def version_warnings(db: Session, version_id: int) -> list[dict]:
    """Things a reviewer must know before approving: missing people, stale leave, inactive staff on duty."""
    v = get_version(db, version_id)
    assign = version_assignments(db, version_id)
    in_roster = {e for (e, _) in assign}
    out: list[dict] = []
    emps = list(db.scalars(select(Employee)))
    missing = [e.employee_id for e in emps if e.is_active and e.employee_id not in in_roster
               and (e.joining_date is None or e.joining_date <= v.end_date)]
    if missing:
        out.append({"type": "missing_employee", "severity": "danger", "employee_ids": missing[:50], "count": len(missing),
                    "message": f"{len(missing)} active employee(s) are not in this roster (added after it was generated?) - re-optimise to include them"})
    gone = {x.employee_id for x in emps if not x.is_active}
    inactive = sorted({e for (e, d), c in assign.items() if e in gone and code_shift(c) and d >= date.today()})
    if inactive:
        out.append({"type": "inactive_on_duty", "severity": "danger", "employee_ids": inactive[:50], "count": len(inactive),
                    "message": f"{len(inactive)} deactivated employee(s) still have future duty in this roster"})
    stale = []
    for lv in db.scalars(select(LeaveApplication).where(
            LeaveApplication.status == "Approved", LeaveApplication.start_date <= v.end_date,
            LeaveApplication.end_date >= v.start_date)):
        d = max(lv.start_date, v.start_date)
        while d <= min(lv.end_date, v.end_date):
            c = assign.get((lv.employee_id, d))
            if c is not None and code_shift(c) and not lv.half_day:
                stale.append(f"{lv.employee_id} {d}")
            d += timedelta(days=1)
    if stale:
        out.append({"type": "leave_not_applied", "severity": "danger", "count": len(stale), "examples": stale[:10],
                    "message": f"{len(stale)} duty day(s) fall inside approved leave - this version predates the leave approval"})
    pend = db.scalar(select(func.count()).select_from(LeaveApplication).where(
        LeaveApplication.status == "Pending", LeaveApplication.start_date <= v.end_date, LeaveApplication.end_date >= v.start_date))
    if pend:
        out.append({"type": "pending_leave", "severity": "info", "count": pend,
                    "message": f"{pend} pending leave application(s) overlap this roster and are not applied yet"})
    # shifts nobody on the roster is eligible for on some day (cannot be fixed by re-optimising)
    for flagname, label, shift in (("is_shift_eligible_night", "Night", "N"),):
        if not any(getattr(e, flagname) and e.is_active for e in emps):
            out.append({"type": "no_eligible", "severity": "danger", "message": f"No active employee is eligible for the {label} shift"})
    return out


def version_history(db: Session, version_id: int) -> dict:
    """Every version of this roster window (old ones stay readable) + the audit trail around them."""
    from app.models.roster import AuditLog
    v = get_version(db, version_id)
    versions = db.scalars(select(RosterVersion).where(RosterVersion.roster_key == v.roster_key)
                          .order_by(RosterVersion.version_no)).all()
    ids = [x.id for x in versions]
    events = db.scalars(select(AuditLog).where(AuditLog.version_id.in_(ids)).order_by(AuditLog.id)).all()
    return {
        "roster_key": v.roster_key, "current_version_id": version_id,
        "versions": [{"id": x.id, "version_no": x.version_no, "status": x.status, "trigger": x.trigger, "reason": x.reason,
                      "base_version_id": x.base_version_id, "created_by": x.created_by, "created_at": x.created_at.isoformat() if x.created_at else None,
                      "approved_by": x.approved_by, "approved_at": x.approved_at.isoformat() if x.approved_at else None,
                      "review_note": x.review_note, "published_by": x.published_by,
                      "published_at": x.published_at.isoformat() if x.published_at else None,
                      "changes": (x.summary or {}).get("changes", 0),
                      "shortage": (x.summary or {}).get("shortage", {}).get("total", 0)} for x in versions],
        "events": [{"id": e.id, "time": e.created_at.isoformat() if e.created_at else None, "actor": e.actor,
                    "action": e.action, "version_id": e.version_id, "details": e.details} for e in events],
    }


# --------------------------------------------------------------- reports --

def diff_codes(old: dict, new: dict) -> list[dict]:
    out = []
    for key in sorted(set(old) | set(new), key=lambda k: (k[1], k[0])):
        a, b = old.get(key), new.get(key)
        if a != b:
            out.append({"employee_id": key[0], "date": key[1].isoformat(), "from": a, "to": b})
    return out


def _employees_by_id(db: Session, ids) -> dict[str, Employee]:
    return {e.employee_id: e for e in db.scalars(select(Employee).where(Employee.employee_id.in_(list(ids))))}


def coverage_report(db: Session, version_id: int, employees: list[Employee] | None = None) -> dict:
    v = get_version(db, version_id)
    assign = version_assignments(db, version_id)
    emps = {e.employee_id: e for e in employees} if employees else _employees_by_id(db, {k[0] for k in assign})
    reqs = load_requirements(db, v.start_date, v.end_date)
    per_day: dict[date, dict] = {}
    for d in _daterange(v.start_date, v.end_date):
        per_day[d] = {s: {"assigned": 0.0, "senior": 0.0} for s in "MEN"}
    for (emp_id, d), code in assign.items():
        s = code_shift(code)
        if s is None or d not in per_day:
            continue
        per_day[d][s]["assigned"] += code_weight(code)
        e = emps.get(emp_id)
        if e is not None and e.role_pool == RolePool.senior_support:
            per_day[d][s]["senior"] += code_weight(code)

    names = {"M": "morning", "E": "evening", "N": "night"}
    days_out = []
    totals = defaultdict(float)
    short_days = 0
    for d, shifts in per_day.items():
        req = reqs[d]
        need = {"M": req.morning, "E": req.evening, "N": req.night}
        row = {"date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()], "shifts": {}, "shortage_total": 0.0,
               "senior_shortage_total": 0.0}
        for s in "MEN":
            assigned = shifts[s]["assigned"]
            senior = shifts[s]["senior"]
            short = max(0.0, need[s] - assigned)
            min_sen = min(req.min_senior, need[s])
            senior_short = max(0.0, min_sen - senior)
            row["shifts"][names[s]] = {
                "required": need[s], "assigned": assigned, "shortage": short,
                "senior_required": min_sen, "senior_assigned": senior, "senior_shortage": senior_short}
            row["shortage_total"] += short
            row["senior_shortage_total"] += senior_short
            totals[names[s]] += short
            totals["senior"] += senior_short
        row["status"] = "SHORTAGE" if row["shortage_total"] or row["senior_shortage_total"] else "OK"
        short_days += row["status"] == "SHORTAGE"
        days_out.append(row)
    totals_out = {k: totals.get(k, 0.0) for k in ("morning", "evening", "night", "senior")}
    totals_out["total"] = totals_out["morning"] + totals_out["evening"] + totals_out["night"] + totals_out["senior"]
    return {"version_id": version_id, "days": days_out, "totals": totals_out, "days_with_shortage": short_days,
            "has_shortage": short_days > 0}


def fairness_report(db: Session, version_id: int) -> dict:
    v = get_version(db, version_id)
    assign = version_assignments(db, version_id)
    emps = _employees_by_id(db, {k[0] for k in assign})
    stats: dict[str, dict] = {}
    for (emp_id, d), code in sorted(assign.items(), key=lambda kv: kv[0][1]):
        st = stats.setdefault(emp_id, {"M": 0, "E": 0, "N": 0, "half": 0, "leave": 0, "R": 0, "max_streak_N": 0, "_n": 0})
        s = code_shift(code)
        if s:
            st[s] += 1
            st["half"] += code.endswith("-H")
        elif code in ("SL", "CL", "AL"):
            st["leave"] += 1
        elif code == "R":
            st["R"] += 1
        st["_n"] = st["_n"] + 1 if s == "N" else 0
        st["max_streak_N"] = max(st["max_streak_N"], st["_n"])
    rows = []
    for emp_id, st in stats.items():
        e = emps.get(emp_id)
        total = st["M"] + st["E"] + st["N"]
        rows.append({
            "employee_id": emp_id, "employee_name": e.full_name if e else emp_id,
            "role": e.role_pool.value if e else "other", "night_eligible": bool(e and e.is_shift_eligible_night),
            "morning": st["M"], "evening": st["E"], "night": st["N"], "total": total,
            "half_duty": st["half"], "leave_days": st["leave"], "reserve_days": st["R"],
            "max_consecutive_nights": st["max_streak_N"],
            "undesirable_score": 3 * st["N"] + st["E"],
        })
    rows.sort(key=lambda r: r["employee_id"])
    nights = [r["night"] for r in rows if r["night_eligible"]]
    evenings = [r["evening"] for r in rows if r["total"] > 0]
    totals = [r["total"] for r in rows if r["total"] > 0]
    avg_n = sum(nights) / len(nights) if nights else 0.0
    summary = {
        "night_pool": len(nights), "night_min": min(nights, default=0), "night_max": max(nights, default=0),
        "night_spread": (max(nights) - min(nights)) if nights else 0, "night_avg": round(avg_n, 2),
        "evening_spread": (max(evenings) - min(evenings)) if evenings else 0,
        "total_spread": (max(totals) - min(totals)) if totals else 0,
    }
    flagged = [r["employee_id"] for r in rows if r["night_eligible"] and r["night"] > avg_n + 2]
    return {"version_id": version_id, "summary": summary, "overloaded_night": flagged, "employees": rows}


def roster_grid(db: Session, version_id: int) -> dict:
    v = get_version(db, version_id)
    assign = version_assignments(db, version_id)
    emps = _employees_by_id(db, {k[0] for k in assign})
    days = list(_daterange(v.start_date, v.end_date))
    rows = []
    for emp_id in sorted({k[0] for k in assign}):
        e = emps.get(emp_id)
        rows.append({
            "employee_id": emp_id, "employee_name": e.full_name if e else emp_id,
            "role": e.role_pool.value if e else "other", "team": e.team if e else None,
            "codes": [assign.get((emp_id, d), "-") for d in days]})
    return {"days": [{"date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()]} for d in days], "rows": rows}


def version_diff(db: Session, version_id: int, against_id: int | None = None) -> dict:
    v = get_version(db, version_id)
    against = against_id or v.base_version_id
    if not against:
        return {"version_id": version_id, "against": None, "changes": []}
    get_version(db, against)
    return {"version_id": version_id, "against": against,
            "changes": diff_codes(version_assignments(db, against), version_assignments(db, version_id))}


def replacement_candidates(db: Session, version_id: int, work_date: date, shift: str, limit: int = 10) -> list[dict]:
    """Who could cover ``shift`` on ``work_date`` in this version, best option first.

    1 = reserve (R) person   2 = working another shift that has spare cover   3 = on weekly off (call-in, needs consent).
    Excludes leave, not-employed, ineligible people and anyone whose rest rule (Night->Morning) would break."""
    if shift not in ("M", "E", "N"):
        raise RosterError("shift must be M, E or N", 422)
    v = get_version(db, version_id)
    if not (v.start_date <= work_date <= v.end_date):
        raise RosterError("Date is outside this roster", 422)
    assign = version_assignments(db, version_id)
    emps = {e.employee_id: e for e in db.scalars(select(Employee).where(Employee.is_active.is_(True)))}
    cov = coverage_report(db, version_id)
    day = next(d for d in cov["days"] if d["date"] == work_date.isoformat())
    names = {"M": "morning", "E": "evening", "N": "night"}
    spare = {s: day["shifts"][n]["assigned"] - day["shifts"][n]["required"] for s, n in names.items()}
    flag = {"M": "is_shift_eligible_morning", "E": "is_shift_eligible_evening", "N": "is_shift_eligible_night"}[shift]
    fair = defaultdict(int)
    for (eid, d), c in assign.items():
        if code_shift(c) == shift:
            fair[eid] += 1
    out = []
    prev_d, next_d = work_date - timedelta(days=1), work_date + timedelta(days=1)
    for eid, e in emps.items():
        code = assign.get((eid, work_date))
        if code is None or code in ("SL", "CL", "AL", "-") or not getattr(e, flag):
            continue
        if code_shift(code) == shift:
            continue
        if shift == "M" and code_shift(assign.get((eid, prev_d), "")) == "N":
            continue
        if shift == "N" and code_shift(assign.get((eid, next_d), "")) == "M":
            continue
        if code == "R":
            rank, how = 1, "reserve"
        elif code == "WO":
            rank, how = 3, "weekly_off_call_in"
        elif code_shift(code) and spare.get(code_shift(code), 0) >= 1:
            rank, how = 2, f"move_from_{code_shift(code)}"
        else:
            continue  # moving this person would only open a new gap elsewhere
        out.append({"employee_id": eid, "employee_name": e.full_name, "current_code": code, "option": how,
                    "senior": e.role_pool == RolePool.senior_support, "shifts_of_this_type": fair[eid], "_r": rank})
    out.sort(key=lambda r: (r["_r"], r["shifts_of_this_type"], r["employee_id"]))
    for r in out:
        r.pop("_r")
    return out[:limit]


def delete_draft(db: Session, version_id: int, actor: str = "system"):
    v = get_version(db, version_id)
    if v.status not in ("draft", "rejected"):
        raise RosterError(f"A {v.status} roster cannot be deleted (audit history is kept)", 409)
    child = db.scalar(select(RosterVersion.id).where(RosterVersion.base_version_id == version_id).limit(1))
    if child:
        raise RosterError("A newer version is based on this draft", 409)
    db.execute(delete(RosterAssignment).where(RosterAssignment.version_id == version_id))
    audit.log(db, "roster_draft_deleted", "roster_version", version_id,
              {"roster_key": v.roster_key, "version_no": v.version_no}, version_id=None, actor=actor)
    db.delete(v)
    db.commit()
