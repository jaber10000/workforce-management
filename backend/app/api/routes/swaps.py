from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, actor_name, get_db, get_principal, get_today, manager_required
from app.models.roster import SwapRequest
from app.services import swap_service
from app.services.swap_service import SwapError

router = APIRouter(prefix="/swaps", tags=["Shift swaps"])


class SwapCreate(BaseModel):
    requester_id: str | None = Field(default=None, max_length=30)  # employees: defaults to themselves
    counterpart_id: str = Field(max_length=30)
    work_date: date
    reason: str | None = Field(default=None, max_length=500)


class Decision(BaseModel):
    note: str | None = Field(default=None, max_length=500)
    decided_by: str | None = Field(default=None, max_length=100)  # honoured only when auth is disabled


class SwapRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    swap_id: str
    requester_id: str
    counterpart_id: str
    work_date: date
    status: str
    reason: str | None
    decided_by: str | None
    decision_note: str | None
    result_version_id: int | None


def _get(db: Session, swap_id: str) -> SwapRequest:
    sw = db.scalar(select(SwapRequest).where(SwapRequest.swap_id == swap_id))
    if not sw:
        raise HTTPException(404, "Swap request not found")
    return sw


def _run(db: Session, fn, *args, **kw):
    try:
        out = fn(*args, **kw)
        db.commit()
        return out
    except SwapError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, exc.message)


@router.get("", response_model=list[SwapRead])
def list_swaps(status: str | None = None, db: Session = Depends(get_db), p: Principal = Depends(get_principal),
               limit: int = Query(default=100, ge=1, le=500)):
    q = select(SwapRequest)
    if not p.is_reviewer:  # employees see only swaps they are part of
        q = q.where(or_(SwapRequest.requester_id == p.employee_id, SwapRequest.counterpart_id == p.employee_id))
    if status:
        q = q.where(SwapRequest.status == status)
    return db.scalars(q.order_by(SwapRequest.id.desc()).limit(limit)).all()


@router.post("", response_model=SwapRead, status_code=201)
def request_swap(body: SwapCreate, db: Session = Depends(get_db), p: Principal = Depends(get_principal),
                 today: date = Depends(get_today)):
    requester = body.requester_id
    if p.is_manager:
        if not requester:
            raise HTTPException(422, "requester_id is required")
    else:
        if not p.employee_id:
            raise HTTPException(403, "Your account is not linked to an employee")
        if requester and requester != p.employee_id:
            raise HTTPException(403, "You can only request swaps for yourself")
        requester = p.employee_id
    return _run(db, swap_service.create, db, requester=requester, counterpart=body.counterpart_id,
                work_date=body.work_date, reason=body.reason, today=today, actor=p.username,
                skip_counterpart=p.is_manager)


@router.post("/{swap_id}/accept", response_model=SwapRead)
def accept(swap_id: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    sw = _get(db, swap_id)
    if not p.is_manager and p.employee_id != sw.counterpart_id:
        raise HTTPException(403, "Only the colleague asked to swap can respond")
    _run(db, swap_service.respond, db, sw, True, p.username)
    return sw


@router.post("/{swap_id}/decline", response_model=SwapRead)
def decline(swap_id: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    sw = _get(db, swap_id)
    if not p.is_manager and p.employee_id != sw.counterpart_id:
        raise HTTPException(403, "Only the colleague asked to swap can respond")
    _run(db, swap_service.respond, db, sw, False, p.username)
    return sw


@router.post("/{swap_id}/cancel", response_model=SwapRead)
def cancel(swap_id: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    sw = _get(db, swap_id)
    if not p.is_manager and p.employee_id != sw.requester_id:
        raise HTTPException(403, "Only the requester can cancel")
    _run(db, swap_service.cancel, db, sw, p.username)
    return sw


@router.post("/{swap_id}/approve")
def approve(swap_id: str, body: Decision | None = None, db: Session = Depends(get_db),
            p: Principal = Depends(manager_required), today: date = Depends(get_today)):
    body = body or Decision()
    sw = _get(db, swap_id)
    result = _run(db, swap_service.approve, db, sw, actor_name(p, body.decided_by), body.note, today)
    return {"swap": SwapRead.model_validate(sw).model_dump(mode="json"), **result}


@router.post("/{swap_id}/reject", response_model=SwapRead)
def reject(swap_id: str, body: Decision | None = None, db: Session = Depends(get_db),
           p: Principal = Depends(manager_required)):
    body = body or Decision()
    sw = _get(db, swap_id)
    _run(db, swap_service.reject, db, sw, actor_name(p, body.decided_by), body.note)
    return sw
