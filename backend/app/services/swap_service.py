"""Shift swap: two employees exchange their duty on one date.

Flow   requester asks -> counterpart accepts -> manager approves -> the swap is applied as a NEW published
       roster version (the previous published version is kept, marked superseded). Managers may also raise a
       swap directly (the counterpart step is skipped).
Rules  checked again at approval time on the current published roster:
       both must be on duty (full or half) in different shifts with the same duty weight, the date must not be
       in the past, each must be eligible for the other's shift, no Night->Morning, at most 3 consecutive
       nights, and Senior / headcount coverage must not get worse."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.employee import Employee, RolePool
from app.models.roster import RosterAssignment, RosterVersion, SwapRequest
from app.services import audit, roster_service as rs
from app.services.roster_engine import NIGHT_STREAK_MAX, code_shift, code_weight


class SwapError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message, self.status_code = message, status_code


def _published_for(db: Session, d: date) -> RosterVersion | None:
    return db.scalar(select(RosterVersion).where(
        RosterVersion.status == "published", RosterVersion.start_date <= d, RosterVersion.end_date >= d
    ).order_by(RosterVersion.id.desc()).limit(1))


def _next_id(db: Session) -> str:
    n = (db.scalar(select(func.max(SwapRequest.id))) or 0) + 1
    while db.scalar(select(SwapRequest.id).where(SwapRequest.swap_id == f"SW{n:04d}")):
        n += 1
    return f"SW{n:04d}"


def check_swap(db: Session, requester: str, counterpart: str, d: date, today: date) -> tuple[RosterVersion, dict]:
    """Validate against the current published roster. Returns (base_version, new_codes_for_the_two)."""
    if requester == counterpart:
        raise SwapError("Choose a different employee", 422)
    if d < today:
        raise SwapError("Past dates cannot be swapped", 409)
    base = _published_for(db, d)
    if base is None:
        raise SwapError("No published roster covers this date", 409)
    codes = rs.version_assignments(db, base.id)
    a, b = codes.get((requester, d)), codes.get((counterpart, d))
    if a is None or b is None:
        raise SwapError("Both employees must be on the published roster for this date", 409)
    sa, sb = code_shift(a), code_shift(b)
    if not sa or not sb:
        raise SwapError(f"Both must be on duty that day ({requester}: {a}, {counterpart}: {b})", 409)
    if sa == sb:
        raise SwapError("Both employees already work the same shift", 409)
    if code_weight(a) != code_weight(b):
        raise SwapError("A half-duty day cannot be swapped with a full-duty day", 409)
    emps = {e.employee_id: e for e in db.scalars(select(Employee).where(Employee.employee_id.in_([requester, counterpart])))}
    if len(emps) != 2:
        raise SwapError("Employee not found", 404)
    flag = {"M": "is_shift_eligible_morning", "E": "is_shift_eligible_evening", "N": "is_shift_eligible_night"}
    for emp, shift in ((requester, sb), (counterpart, sa)):
        if not getattr(emps[emp], flag[shift]) or not emps[emp].is_active:
            raise SwapError(f"{emp} is not eligible for the {shift} shift", 409)
    new = dict(codes)
    new[(requester, d)], new[(counterpart, d)] = b, a
    for emp in (requester, counterpart):
        prev, nxt = new.get((emp, d - timedelta(days=1)), ""), new.get((emp, d + timedelta(days=1)), "")
        cur = new[(emp, d)]
        if code_shift(prev) == "N" and code_shift(cur) == "M":
            raise SwapError(f"{emp}: Night followed by Morning is not allowed", 409)
        if code_shift(cur) == "N" and code_shift(nxt) == "M":
            raise SwapError(f"{emp}: Night followed by Morning is not allowed", 409)
        streak = 0
        for k in range(-NIGHT_STREAK_MAX, NIGHT_STREAK_MAX + 1):
            streak = streak + 1 if code_shift(new.get((emp, d + timedelta(days=k)), "")) == "N" else 0
            if streak > NIGHT_STREAK_MAX:
                raise SwapError(f"{emp}: more than {NIGHT_STREAK_MAX} consecutive nights", 409)
    # coverage must not get worse (Senior balance can change when a Senior swaps with a non-Senior)
    allemps = {e.employee_id: e for e in db.scalars(select(Employee).where(Employee.employee_id.in_({k[0] for k in codes})))}
    reqs = rs.load_requirements(db, d, d)[d]
    def senior_short(cs):
        out = 0.0
        for s, need in (("M", reqs.morning), ("E", reqs.evening), ("N", reqs.night)):
            have = sum(code_weight(c) for (e, dd), c in cs.items()
                       if dd == d and code_shift(c) == s and allemps.get(e) and allemps[e].role_pool == RolePool.senior_support)
            out += max(0.0, min(reqs.min_senior, need) - have)
        return out
    day = {k: v for k, v in codes.items() if k[1] == d}
    day_new = {k: v for k, v in new.items() if k[1] == d}
    if senior_short(day_new) > senior_short(day):
        raise SwapError("This swap would leave a shift without its minimum Senior cover", 409)
    return base, {"requester_old": a, "counterpart_old": b, "new": new}


def create(db: Session, *, requester: str, counterpart: str, work_date: date, reason: str | None,
           today: date, actor: str, skip_counterpart: bool = False) -> SwapRequest:
    check_swap(db, requester, counterpart, work_date, today)  # fail early with a clear reason
    dup = db.scalar(select(SwapRequest).where(
        SwapRequest.work_date == work_date, SwapRequest.status.in_(("pending_counterpart", "pending_manager")),
        SwapRequest.requester_id.in_([requester, counterpart]) | SwapRequest.counterpart_id.in_([requester, counterpart])))
    if dup:
        raise SwapError(f"{dup.swap_id} already involves one of them on this date", 409)
    sw = SwapRequest(swap_id=_next_id(db), requester_id=requester, counterpart_id=counterpart, work_date=work_date,
                     reason=reason, created_by=actor,
                     status="pending_manager" if skip_counterpart else "pending_counterpart")
    db.add(sw)
    db.flush()
    audit.log(db, "swap_requested", "swap", sw.swap_id,
              {"requester": requester, "counterpart": counterpart, "date": str(work_date), "reason": reason},
              actor=actor)
    return sw


def respond(db: Session, sw: SwapRequest, accept: bool, actor: str):
    if sw.status != "pending_counterpart":
        raise SwapError(f"Not waiting for the counterpart (status: {sw.status})", 409)
    sw.status = "pending_manager" if accept else "declined"
    if not accept:
        sw.decided_by, sw.decided_at = actor, rs._now()
    audit.log(db, "swap_accepted" if accept else "swap_declined", "swap", sw.swap_id, {"date": str(sw.work_date)}, actor=actor)


def cancel(db: Session, sw: SwapRequest, actor: str):
    if sw.status not in ("pending_counterpart", "pending_manager"):
        raise SwapError(f"Cannot cancel a {sw.status} swap", 409)
    sw.status, sw.decided_by, sw.decided_at = "cancelled", actor, rs._now()
    audit.log(db, "swap_cancelled", "swap", sw.swap_id, {}, actor=actor)


def reject(db: Session, sw: SwapRequest, actor: str, note: str | None):
    if sw.status not in ("pending_counterpart", "pending_manager"):
        raise SwapError(f"Cannot reject a {sw.status} swap", 409)
    sw.status, sw.decided_by, sw.decided_at, sw.decision_note = "rejected", actor, rs._now(), note
    audit.log(db, "swap_rejected", "swap", sw.swap_id, {"note": note}, actor=actor)


def approve(db: Session, sw: SwapRequest, actor: str, note: str | None, today: date) -> dict:
    if sw.status != "pending_manager":
        raise SwapError(f"Swap is not waiting for manager approval (status: {sw.status})", 409)
    base, info = check_swap(db, sw.requester_id, sw.counterpart_id, sw.work_date, today)
    new = info["new"]
    key = base.roster_key
    version_no = (db.scalar(select(func.max(RosterVersion.version_no)).where(RosterVersion.roster_key == key)) or 0) + 1
    nv = RosterVersion(
        roster_key=key, version_no=version_no, start_date=base.start_date, end_date=base.end_date,
        status="published", trigger="shift_swap", reason=f"{sw.swap_id}: {sw.requester_id} <-> {sw.counterpart_id} on {sw.work_date}",
        base_version_id=base.id, lock_before=today, solver_status="swap", objective=None, solve_seconds=0.0,
        summary=dict(base.summary or {}), created_by=actor, approved_by=actor, approved_at=rs._now(),
        published_by=actor, published_at=rs._now())
    db.add(nv)
    db.flush()
    rows = db.execute(select(RosterAssignment.employee_id, RosterAssignment.work_date, RosterAssignment.code,
                             RosterAssignment.weight).where(RosterAssignment.version_id == base.id)).all()
    db.bulk_insert_mappings(RosterAssignment, [
        {"version_id": nv.id, "employee_id": e, "work_date": d, "code": new[(e, d)], "weight": w} for e, d, c, w in rows])
    base.status = "superseded"
    sw.status, sw.decided_by, sw.decided_at, sw.decision_note, sw.result_version_id = "approved", actor, rs._now(), note, nv.id
    db.flush()
    cov = rs.coverage_report(db, nv.id)
    nv.summary = {**(nv.summary or {}), "shortage": cov["totals"], "days_with_shortage": cov["days_with_shortage"],
                  "changes": 2}
    stale = [v.id for v in db.scalars(select(RosterVersion).where(
        RosterVersion.roster_key == key, RosterVersion.status.in_(("draft", "approved")), RosterVersion.id != nv.id))]
    audit.log(db, "swap_approved", "swap", sw.swap_id,
              {"date": str(sw.work_date), "requester": sw.requester_id, "counterpart": sw.counterpart_id,
               "requester_code": f"{info['requester_old']}->{info['counterpart_old']}",
               "counterpart_code": f"{info['counterpart_old']}->{info['requester_old']}",
               "base_version_id": base.id, "new_version_id": nv.id, "note": note}, version_id=nv.id, actor=actor)
    return {"new_version_id": nv.id, "base_version_id": base.id,
            "open_drafts_based_on_old_version": stale,
            "warning": ("Open draft/approved versions " + ", ".join(f"#{i}" for i in stale) +
                        " were built before this swap; re-optimise or review them.") if stale else None}
