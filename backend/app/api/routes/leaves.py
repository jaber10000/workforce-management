from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, actor_name, get_db, get_principal, get_today, manager_required
from app.models.leave import LeaveApplication
from app.schemas.leave import (LeaveBalanceRead, LeaveCreate, LeaveDecision, LeavePage, LeaveRead)
from app.services import leave_service, roster_service
from app.services.leave_service import LeaveError

router = APIRouter(prefix="/leaves", tags=["Leaves"], dependencies=[Depends(get_principal)])


def _get(db: Session, application_id: str) -> LeaveApplication:
    lv = db.scalar(select(LeaveApplication).where(LeaveApplication.application_id == application_id))
    if not lv:
        raise HTTPException(404, "Leave application not found")
    return lv


def _own_or_manager(p: Principal, employee_id: str):
    if not p.is_manager and p.employee_id != employee_id:
        raise HTTPException(403, "You can only access your own leave")


def _own_or_reviewer(p: Principal, employee_id: str):
    """Read access: own record, or any record for manager/supervisor reviewers."""
    if not p.is_reviewer and p.employee_id != employee_id:
        raise HTTPException(403, "You can only access your own leave")


def _raise(exc: LeaveError):
    raise HTTPException(exc.status_code, exc.message)


@router.get("", response_model=LeavePage)
def list_leaves(employee_id: str | None = None, status_: str | None = Query(default=None, alias="status"),
                from_date: date | None = None, to_date: date | None = None,
                skip: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=500),
                db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    if not p.is_reviewer:  # employees only ever see their own applications
        employee_id = p.employee_id or "__none__"
    stmt, cnt = select(LeaveApplication), select(func.count()).select_from(LeaveApplication)
    conds = []
    if employee_id:
        conds.append(LeaveApplication.employee_id == employee_id)
    if status_:
        conds.append(LeaveApplication.status == status_)
    if from_date:
        conds.append(LeaveApplication.end_date >= from_date)
    if to_date:
        conds.append(LeaveApplication.start_date <= to_date)
    for c in conds:
        stmt, cnt = stmt.where(c), cnt.where(c)
    items = db.scalars(stmt.order_by(LeaveApplication.start_date.desc(), LeaveApplication.id.desc())
                       .offset(skip).limit(limit)).all()
    return LeavePage(items=items, total=db.scalar(cnt) or 0, skip=skip, limit=limit)


@router.get("/balance/{employee_id}", response_model=list[LeaveBalanceRead])
def balance(employee_id: str, year: int | None = None, db: Session = Depends(get_db),
            today: date = Depends(get_today), p: Principal = Depends(get_principal)):
    _own_or_reviewer(p, employee_id)
    from app.models.employee import Employee
    if not db.scalar(select(Employee.id).where(Employee.employee_id == employee_id)):
        raise HTTPException(404, "Employee not found")
    data = leave_service.get_balances(db, employee_id, year or today.year)
    db.commit()
    return data


@router.post("", response_model=LeaveRead, status_code=status.HTTP_201_CREATED)
def apply(payload: LeaveCreate, db: Session = Depends(get_db), p: Principal = Depends(get_principal),
          today: date = Depends(get_today)):
    _own_or_manager(p, payload.employee_id)
    try:
        lv = leave_service.apply_leave(db, **payload.model_dump(), actor=p.username, today=today,
                                       is_manager=p.is_manager)
        db.commit()
    except LeaveError as exc:
        db.rollback()
        _raise(exc)
    db.refresh(lv)
    return lv


@router.get("/{application_id}", response_model=LeaveRead)
def get_leave(application_id: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    lv = _get(db, application_id)
    _own_or_reviewer(p, lv.employee_id)
    return lv


@router.post("/{application_id}/preview")
def preview(application_id: str, time_limit_seconds: float = Query(default=15, ge=1, le=120),
            db: Session = Depends(get_db), today: date = Depends(get_today), p: Principal = Depends(manager_required)):
    """What would approval do? Runs the real re-optimisation, saves nothing."""
    lv = _get(db, application_id)
    try:
        return leave_service.simulate_approval(db, lv, today, time_limit_seconds)
    except LeaveError as exc:
        _raise(exc)


@router.get("/{application_id}/impact")
def impact(application_id: str, db: Session = Depends(get_db), p: Principal = Depends(manager_required)):
    """Roster impact recorded when the leave was approved/cancelled."""
    _get(db, application_id)
    return {"application_id": application_id, "impact": leave_service.last_impact(db, application_id)}


@router.post("/{application_id}/approve")
def approve(application_id: str, body: LeaveDecision | None = None, db: Session = Depends(get_db),
            today: date = Depends(get_today), p: Principal = Depends(manager_required)):
    body = body or LeaveDecision()
    body.decided_by = actor_name(p, body.decided_by)
    lv = _get(db, application_id)
    try:
        leave_service.approve(db, lv, body.decided_by, body.note)
        db.commit()
    except LeaveError as exc:
        db.rollback()
        _raise(exc)
    db.refresh(lv)
    return {"leave": LeaveRead.model_validate(lv).model_dump(mode="json"),
            **leave_service.roster_sync(db, lv, "leave_approved", body.auto_roster, today, body.decided_by)}


@router.post("/{application_id}/reject", response_model=LeaveRead)
def reject(application_id: str, body: LeaveDecision | None = None, db: Session = Depends(get_db),
           p: Principal = Depends(manager_required)):
    body = body or LeaveDecision()
    body.decided_by = actor_name(p, body.decided_by)
    lv = _get(db, application_id)
    try:
        leave_service.reject(db, lv, body.decided_by, body.note)
        db.commit()
    except LeaveError as exc:
        db.rollback()
        _raise(exc)
    db.refresh(lv)
    return lv


@router.post("/{application_id}/cancel")
def cancel(application_id: str, body: LeaveDecision | None = None, db: Session = Depends(get_db),
           today: date = Depends(get_today), p: Principal = Depends(get_principal)):
    body = body or LeaveDecision()
    body.decided_by = actor_name(p, body.decided_by)
    lv = _get(db, application_id)
    _own_or_manager(p, lv.employee_id)
    if not p.is_manager and lv.status != "Pending":
        raise HTTPException(403, "Only a manager can cancel an approved leave")
    try:
        was_approved = leave_service.cancel(db, lv, body.decided_by, body.note)
        db.commit()
    except LeaveError as exc:
        db.rollback()
        _raise(exc)
    db.refresh(lv)
    sync = (leave_service.roster_sync(db, lv, "leave_cancelled", body.auto_roster, today, body.decided_by)
            if was_approved else {"roster_version": None, "roster_adjustment": "not needed", "impact": None})
    return {"leave": LeaveRead.model_validate(lv).model_dump(mode="json"), **sync}
