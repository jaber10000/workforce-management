"""Leave application, approval and balance rules."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.leave_policy import LEAVE_POLICY, LEAVE_TYPES
from app.models.employee import Employee
from app.models.leave import LeaveApplication, LeaveBalance
from app.schemas.roster import VersionRead
from app.services import audit, offday_planner, roster_service
from app.services.roster_engine import code_shift
from app.services.roster_service import RosterError


class LeaveError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def compute_days(leave_type: str, start: date, end: date, half_day: bool) -> float:
    if end < start:
        raise LeaveError("End date cannot be before start date", 422)
    if half_day:
        if not LEAVE_POLICY[leave_type]["half_day_allowed"]:
            raise LeaveError(f"{leave_type} leave cannot be taken as a half day", 422)
        if start != end:
            raise LeaveError("A half-day leave must be a single day", 422)
        return 0.5
    return float((end - start).days + 1)


def _days_in_year(lv: LeaveApplication, year: int) -> float:
    if lv.half_day:
        return 0.5 if lv.start_date.year == year else 0.0
    lo, hi = max(lv.start_date, date(year, 1, 1)), min(lv.end_date, date(year, 12, 31))
    return float((hi - lo).days + 1) if hi >= lo else 0.0


def _consumed(db: Session, employee_id: str, year: int, leave_type: str, statuses: tuple[str, ...]) -> float:
    rows = db.scalars(select(LeaveApplication).where(
        LeaveApplication.employee_id == employee_id,
        LeaveApplication.leave_type == leave_type,
        LeaveApplication.status.in_(statuses),
        LeaveApplication.start_date <= date(year, 12, 31),
        LeaveApplication.end_date >= date(year, 1, 1),
    )).all()
    return sum(_days_in_year(r, year) for r in rows)


def ensure_balance(db: Session, employee_id: str, year: int, leave_type: str) -> LeaveBalance:
    """Return the balance row, creating it from the policy (with carry-forward) when missing."""
    row = db.scalar(select(LeaveBalance).where(
        LeaveBalance.employee_id == employee_id, LeaveBalance.year == year,
        LeaveBalance.leave_type == leave_type))
    if row:
        return row
    policy = LEAVE_POLICY[leave_type]
    carried = 0.0
    prev = db.scalar(select(LeaveBalance).where(
        LeaveBalance.employee_id == employee_id, LeaveBalance.year == year - 1,
        LeaveBalance.leave_type == leave_type))
    if prev and policy["carry_forward_max"] > 0:
        remaining = prev.entitlement + prev.carried_forward - _consumed(
            db, employee_id, year - 1, leave_type, ("Approved",))
        carried = min(max(remaining, 0.0), policy["carry_forward_max"])
    row = LeaveBalance(employee_id=employee_id, year=year, leave_type=leave_type,
                       entitlement=policy["entitlement"], carried_forward=carried)
    db.add(row)
    db.flush()
    return row


def get_balances(db: Session, employee_id: str, year: int) -> list[dict]:
    out = []
    for leave_type in LEAVE_TYPES:
        b = ensure_balance(db, employee_id, year, leave_type)
        used = _consumed(db, employee_id, year, leave_type, ("Approved",))
        pending = _consumed(db, employee_id, year, leave_type, ("Pending",))
        total = b.entitlement + b.carried_forward
        out.append({
            "leave_type": leave_type, "year": year, "entitlement": b.entitlement,
            "carried_forward": b.carried_forward, "total": total, "used": used,
            "pending": pending, "remaining": total - used, "available": total - used - pending,
            "half_day_allowed": LEAVE_POLICY[leave_type]["half_day_allowed"],
        })
    return out


def _check_balance(db: Session, lv: LeaveApplication, *, include_pending: bool, exclude_self: bool = False):
    """Every calendar year touched by the leave must have enough balance."""
    for year in range(lv.start_date.year, lv.end_date.year + 1):
        need = _days_in_year(lv, year)
        if need <= 0:
            continue
        b = ensure_balance(db, lv.employee_id, year, lv.leave_type)
        statuses = ("Approved", "Pending") if include_pending else ("Approved",)
        used = _consumed(db, lv.employee_id, year, lv.leave_type, statuses)
        if exclude_self and lv.status in statuses:
            used -= need
        if used + need > b.entitlement + b.carried_forward + 1e-9:
            left = b.entitlement + b.carried_forward - used
            raise LeaveError(
                f"Insufficient {lv.leave_type} leave balance for {year}: need {need:g}, available {max(left, 0):g}", 409)


def _next_application_id(db: Session) -> str:
    n = db.scalar(select(func.max(LeaveApplication.id))) or 0
    candidate = n + 1
    while db.scalar(select(LeaveApplication.id).where(
            LeaveApplication.application_id == f"LV{candidate:04d}")):
        candidate += 1
    return f"LV{candidate:04d}"


def validate_dates(start: date, end: date, today: date, *, is_manager: bool = True) -> None:
    """Reject impossible / absurd leave dates with a message the user can act on."""
    from app.core.config import settings
    if end < start:
        raise LeaveError("End date cannot be before start date", 422)
    if start.year < 2000:
        raise LeaveError(f"{start} is not a valid leave date", 422)
    if end > date.fromordinal(today.toordinal() + settings.leave_max_future_days):
        raise LeaveError(f"Leave cannot be applied more than {settings.leave_max_future_days} days ahead", 422)
    if (end - start).days + 1 > settings.leave_max_span_days:
        raise LeaveError(f"One application can cover at most {settings.leave_max_span_days} days - split it", 422)
    if not is_manager and start < date.fromordinal(today.toordinal() - settings.leave_max_backdate_days):
        raise LeaveError(f"Leave older than {settings.leave_max_backdate_days} days must be entered by a manager", 422)


def apply_leave(db: Session, *, employee_id: str, leave_type: str, start_date: date, end_date: date,
                half_day: bool = False, reason: str | None = None, actor: str = "system",
                today: date | None = None, is_manager: bool = True) -> LeaveApplication:
    if leave_type not in LEAVE_TYPES:
        raise LeaveError(f"Unknown leave type '{leave_type}'", 422)
    validate_dates(start_date, end_date, today or date.today(), is_manager=is_manager)
    emp = db.scalar(select(Employee).where(Employee.employee_id == employee_id))
    if not emp:
        raise LeaveError("Employee not found", 404)
    if not emp.is_active:
        raise LeaveError("Employee is inactive", 409)
    days = compute_days(leave_type, start_date, end_date, half_day)
    overlap = db.scalar(select(LeaveApplication).where(
        LeaveApplication.employee_id == employee_id,
        LeaveApplication.status.in_(("Pending", "Approved")),
        LeaveApplication.start_date <= end_date, LeaveApplication.end_date >= start_date))
    if overlap:
        raise LeaveError(f"Overlaps existing leave {overlap.application_id} ({overlap.status})", 409)
    lv = LeaveApplication(application_id=_next_application_id(db), employee_id=employee_id,
                          leave_type=leave_type, start_date=start_date, end_date=end_date,
                          half_day=half_day, days=days, status="Pending", reason=reason)
    _check_balance(db, lv, include_pending=True)
    db.add(lv)
    audit.log(db, "leave_applied", "leave", lv.application_id,
              {"employee_id": employee_id, "type": leave_type, "from": str(start_date),
               "to": str(end_date), "days": days}, actor=actor)
    db.flush()
    return lv


def _decide(db: Session, lv: LeaveApplication, status: str, actor: str, note: str | None):
    lv.status = status
    lv.decided_by = actor
    lv.decided_at = datetime.now(timezone.utc)
    lv.decision_note = note
    audit.log(db, f"leave_{status.lower()}", "leave", lv.application_id,
              {"employee_id": lv.employee_id, "from": str(lv.start_date), "to": str(lv.end_date)}, actor=actor)


def approve(db: Session, lv: LeaveApplication, actor: str = "system", note: str | None = None):
    if lv.status != "Pending":
        raise LeaveError(f"Only Pending leave can be approved (current: {lv.status})", 409)
    _check_balance(db, lv, include_pending=False)
    _decide(db, lv, "Approved", actor, note)


def reject(db: Session, lv: LeaveApplication, actor: str = "system", note: str | None = None):
    if lv.status != "Pending":
        raise LeaveError(f"Only Pending leave can be rejected (current: {lv.status})", 409)
    _decide(db, lv, "Rejected", actor, note)


def cancel(db: Session, lv: LeaveApplication, actor: str = "system", note: str | None = None) -> bool:
    """Cancel a Pending or Approved leave. Returns True when an approved leave was released."""
    if lv.status not in ("Pending", "Approved"):
        raise LeaveError(f"Cannot cancel a {lv.status} leave", 409)
    was_approved = lv.status == "Approved"
    _decide(db, lv, "Cancelled", actor, note)
    return was_approved


# ------------------------------------------------------------ roster sync --

LEAVE_CODES = ("SL", "CL", "AL")


def _shortage_rows(cov: dict, dates: set[str] | None = None) -> list[dict]:
    rows = []
    for d in cov["days"]:
        if dates is not None and d["date"] not in dates:
            continue
        for shift, name in (("M", "morning"), ("E", "evening"), ("N", "night")):
            x = d["shifts"][name]
            if x["shortage"] > 0 or x["senior_shortage"] > 0:
                rows.append({"date": d["date"], "shift": shift, "required": x["required"], "assigned": x["assigned"],
                             "shortage": x["shortage"], "senior_required": x["senior_required"],
                             "senior_assigned": x["senior_assigned"], "senior_shortage": x["senior_shortage"]})
    return rows


def build_impact(db: Session, lv: LeaveApplication, base_id: int, new_id: int, off_plan: dict | None) -> dict:
    """What approving the leave does to the roster: removed duty, who replaces whom, what is still short."""
    base_codes = roster_service.version_assignments(db, base_id)
    new_codes = roster_service.version_assignments(db, new_id)
    changes = roster_service.diff_codes(base_codes, new_codes)
    lo, hi = lv.start_date.isoformat(), lv.end_date.isoformat()
    removed, replacements, own_other, others = [], [], [], []
    for c in changes:
        mine = c["employee_id"] == lv.employee_id
        if mine and lo <= c["date"] <= hi and c["to"] in LEAVE_CODES:
            if code_shift(c["from"] or "") or c["from"] == "R":
                removed.append({"date": c["date"], "was": c["from"]})
        elif mine:
            own_other.append(c)  # e.g. weekly off moved after a long leave
        elif code_shift(c["to"] or "") and code_shift(c["from"] or "") != code_shift(c["to"] or ""):
            how = {"R": "from_reserve", "WO": "weekly_off_call_in"}.get(c["from"], "moved_shift")
            replacements.append({"date": c["date"], "shift": code_shift(c["to"]), "employee_id": c["employee_id"],
                                 "from": c["from"], "to": c["to"], "how": how})
        else:
            others.append(c)
    cov_new = roster_service.coverage_report(db, new_id)
    cov_old = roster_service.coverage_report(db, base_id)
    touched = {c["date"] for c in changes} | {r["date"] for r in removed}
    shortages = _shortage_rows(cov_new, touched | {d for d in (lo, hi)})
    proposals = []
    for row in shortages[:10]:
        try:
            cands = roster_service.replacement_candidates(db, new_id, date.fromisoformat(row["date"]), row["shift"], 5)
        except RosterError:
            cands = []
        if row["shortage"] <= 0:  # senior-only gap: suggest senior people
            cands = [c for c in cands if c["senior"]]
        proposals.append({"date": row["date"], "shift": row["shift"], "missing": row["shortage"],
                          "senior_missing": row["senior_shortage"], "candidates": cands})
    return {
        "application_id": lv.application_id, "employee_id": lv.employee_id,
        "from": lo, "to": hi, "base_version_id": base_id, "new_version_id": new_id,
        "removed_assignments": removed, "replacements": replacements[:300],
        "employee_other_changes": own_other[:100], "other_changes": others[:100],
        "change_total": len(changes), "other_employees_changed": len({c["employee_id"] for c in changes} - {lv.employee_id}),
        "shortages": shortages[:100], "shortage_total_before": cov_old["totals"]["total"],
        "shortage_total_after": cov_new["totals"]["total"], "proposals": proposals, "off_day_plan": off_plan,
    }


def roster_sync(db: Session, lv: LeaveApplication, trigger: str, auto: bool, today: date, actor: str,
                commit: bool = True, time_limit: float | None = None) -> dict:
    """After approve/cancel: long-leave off-day re-plan, then a minimal-change roster re-optimisation
    (new draft version). Never fails the leave action itself."""
    off_plan = None
    removed_plans = 0
    if trigger == "leave_approved":
        off_plan = offday_planner.replan_after_long_leave(db, lv, actor)
    elif trigger == "leave_cancelled":
        removed_plans = offday_planner.remove_plans(db, lv, today, actor)
    if commit:
        db.commit()  # leave decision + off-day plan are durable even if the solver fails below
    result = {"roster_version": None, "roster_adjustment": "skipped", "impact": None, "off_day_plan": off_plan,
              "off_day_plans_removed": removed_plans}
    if not auto:
        return result
    to_date = lv.end_date
    if off_plan:
        to_date = max(to_date, date.fromisoformat(off_plan["effective_from"]))
    try:
        base = roster_service.latest_version(db, lv.start_date, to_date)
        base_id = base.id if base else None
        version = roster_service.auto_adjust(
            db, trigger=trigger, from_date=lv.start_date, to_date=to_date, today=today, actor=actor,
            reason=f"{lv.application_id} {lv.employee_id} {lv.leave_type} leave {lv.start_date}..{lv.end_date}",
            time_limit=time_limit, commit=commit)
    except RosterError as exc:
        db.rollback()
        result["roster_adjustment"] = f"failed: {exc.message}"
        return result
    if version is None:
        result["roster_adjustment"] = ("no roster change needed (no roster covers these dates, "
                                       "or they are already past)")
        return result
    result["roster_version"] = VersionRead.model_validate(version).model_dump(mode="json")
    result["roster_adjustment"] = "new draft version created"
    result["impact"] = build_impact(db, lv, base_id, version.id, off_plan)
    if commit:
        audit.log(db, "leave_roster_impact", "leave", lv.application_id, result["impact"], version_id=version.id,
                  actor=actor)
        db.commit()
    return result


def simulate_approval(db: Session, lv: LeaveApplication, today: date, time_limit: float | None = None) -> dict:
    """What-if: run the real approval + re-optimisation inside a transaction and roll everything back."""
    if lv.status != "Pending":
        raise LeaveError(f"Only Pending leave can be previewed (current: {lv.status})", 409)
    _check_balance(db, lv, include_pending=False)
    lv_id = lv.application_id
    try:
        lv.status = "Approved"
        db.flush()
        result = roster_sync(db, lv, "leave_approved", True, today, "simulation", commit=False,
                             time_limit=time_limit)
    finally:
        db.rollback()
    result.pop("roster_version", None)  # the would-be version is not saved
    if result.get("impact"):
        result["impact"]["new_version_id"] = None
    result.update(simulated=True, application_id=lv_id)
    return result


def last_impact(db: Session, application_id: str) -> dict | None:
    from app.models.roster import AuditLog
    row = db.scalar(select(AuditLog).where(AuditLog.entity_type == "leave", AuditLog.entity_id == application_id,
                                           AuditLog.action == "leave_roster_impact").order_by(AuditLog.id.desc()).limit(1))
    return row.details if row else None
