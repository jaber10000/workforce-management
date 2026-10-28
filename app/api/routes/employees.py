from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from datetime import date

from app.api.deps import Principal, get_db, get_principal, get_today, manager_required
from app.services import audit, roster_service
from app.services.roster_service import RosterError
from app.models.employee import Employee, RolePool
from app.schemas.employee import EmployeeCreate, EmployeePage, EmployeeRead, EmployeeUpdate

router = APIRouter(prefix="/employees", tags=["Employees"], dependencies=[Depends(get_principal)])


def _auto_adjust(db: Session, trigger: str, employee: Employee, today: date, actor: str = "system") -> None:
    """New / removed employee -> coverage re-check and a new roster version (never fails the request)."""
    start = max(employee.joining_date or today, today) if trigger == "employee_added" else today
    try:
        roster_service.auto_adjust(
            db, trigger=trigger, from_date=start, to_date=date.max,
            reason=f"{trigger.replace('_', ' ')}: {employee.employee_id}", today=today, actor=actor)
    except RosterError:
        db.rollback()


def _self_view(e: Employee) -> dict:
    """What an employee may see about themselves (manager-only notes are hidden)."""
    data = EmployeeRead.model_validate(e).model_dump(mode="json")
    data["notes"] = None
    return data


def _supervisor_view(e: Employee) -> dict:
    """Supervisors review rosters but do not see private contact data (phone, home thana, notes)."""
    data = EmployeeRead.model_validate(e).model_dump(mode="json")
    data["phone_number"] = data["home_thana"] = data["notes"] = None
    return data


@router.get("/directory")
def directory(db: Session = Depends(get_db)):
    """Names only (no phone, address, notes) - what an employee needs to pick a swap colleague."""
    rows = db.execute(select(Employee.employee_id, Employee.full_name, Employee.role_pool)
                      .where(Employee.is_active.is_(True)).order_by(Employee.employee_id)).all()
    return [{"employee_id": r[0], "full_name": r[1], "role_pool": r[2].value} for r in rows]


@router.get("", response_model=EmployeePage)
def list_employees(
    search: str | None = Query(default=None, max_length=150),
    role_pool: RolePool | None = None,
    is_active: bool | None = True,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    p: Principal = Depends(get_principal),
):
    if not p.is_reviewer:  # employees see only their own record; the name-only /directory serves everything else
        mine = db.scalar(select(Employee).where(Employee.employee_id == (p.employee_id or "__none__")))
        items = [_self_view(mine)] if mine else []
        return {"items": items, "total": len(items), "skip": 0, "limit": limit}
    private = not p.is_manager  # supervisor: no phone / thana / notes, and no searching through them
    stmt = select(Employee)
    count_stmt = select(func.count()).select_from(Employee)

    if is_active is not None:
        stmt = stmt.where(Employee.is_active == is_active)
        count_stmt = count_stmt.where(Employee.is_active == is_active)
    if role_pool is not None:
        stmt = stmt.where(Employee.role_pool == role_pool)
        count_stmt = count_stmt.where(Employee.role_pool == role_pool)
    if search:
        pattern = f"%{search.strip()}%"
        fields = [Employee.employee_id.ilike(pattern), Employee.full_name.ilike(pattern)]
        if not private:
            fields += [Employee.phone_number.ilike(pattern), Employee.home_thana.ilike(pattern)]
        condition = or_(*fields)
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = db.scalar(count_stmt) or 0
    items = db.scalars(stmt.order_by(Employee.employee_id).offset(skip).limit(limit)).all()
    if private:
        items = [_supervisor_view(e) for e in items]
    return EmployeePage(items=items, total=total, skip=skip, limit=limit)


@router.get("/{employee_id}", response_model=EmployeeRead)
def get_employee(employee_id: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    if not p.is_reviewer and p.employee_id != employee_id:
        raise HTTPException(status_code=403, detail="You can only view your own employee record")
    employee = db.scalar(select(Employee).where(Employee.employee_id == employee_id))
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    if p.is_manager:
        return employee
    return _supervisor_view(employee) if p.is_reviewer else _self_view(employee)


@router.post("", response_model=EmployeeRead, status_code=status.HTTP_201_CREATED)
def create_employee(payload: EmployeeCreate, auto_roster: bool = True, db: Session = Depends(get_db),
                    today: date = Depends(get_today), p: Principal = Depends(manager_required)):
    if db.scalar(select(Employee.id).where(func.lower(Employee.employee_id) == payload.employee_id.lower())):
        raise HTTPException(status_code=409, detail=f"Employee ID '{payload.employee_id}' already exists")
    employee = Employee(**payload.model_dump())
    db.add(employee)
    try:
        db.commit()
        db.refresh(employee)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Employee ID '{payload.employee_id}' already exists")
    audit.log(db, "employee_created", "employee", employee.employee_id, {"name": employee.full_name}, actor=p.username)
    db.commit()
    if auto_roster and employee.is_active:
        _auto_adjust(db, "employee_added", employee, today, p.username)
    return employee


@router.patch("/{employee_id}", response_model=EmployeeRead)
def update_employee(employee_id: str, payload: EmployeeUpdate, db: Session = Depends(get_db),
                    p: Principal = Depends(manager_required)):
    employee = db.scalar(select(Employee).where(Employee.employee_id == employee_id))
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    changes = payload.model_dump(exclude_unset=True)
    before = {k: str(getattr(employee, k)) for k in changes}
    for key, value in changes.items():
        setattr(employee, key, value)
    audit.log(db, "employee_updated", "employee", employee_id,
              {"before": before, "after": {k: str(v) for k, v in changes.items()}}, actor=p.username)
    try:
        db.commit()
        db.refresh(employee)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Employee update conflicts with existing data")
    return employee


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_employee(employee_id: str, auto_roster: bool = True, db: Session = Depends(get_db),
                        today: date = Depends(get_today), p: Principal = Depends(manager_required)):
    employee = db.scalar(select(Employee).where(Employee.employee_id == employee_id))
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    # Soft delete preserves history for future roster/audit modules.
    employee.is_active = False
    audit.log(db, "employee_deactivated", "employee", employee_id, {}, actor=p.username)
    db.commit()
    if auto_roster:
        _auto_adjust(db, "employee_deactivated", employee, today, p.username)
    return None
