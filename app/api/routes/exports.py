"""Excel export endpoints (Step 7). Managers: everything. Employees: only the weekly roster of a published version."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_db, get_principal, get_today, manager_required
from app.models.employee import RolePool
from app.services import audit, export_service as ex
from app.services.roster_service import RosterError

router = APIRouter(prefix="/exports", tags=["Excel export"])


def _send(db: Session, p: Principal, data: bytes, name: str, kind: str, details: dict, version_id: int | None = None):
    audit.log(db, "report_exported", "report", kind, {**details, "file": name}, version_id=version_id, actor=p.username)
    db.commit()
    return Response(data, media_type=ex.XLSX_MIME, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/roster/weekly.xlsx")
def weekly_roster(week_start: date | None = None, version_id: int | None = None, db: Session = Depends(get_db),
                  today: date = Depends(get_today), p: Principal = Depends(get_principal)):
    """One week (7 days from week_start; default: this week's Monday) of a roster version."""
    ws_ = week_start or (today - timedelta(days=today.weekday()))
    try:
        v = ex.pick_version(db, version_id=version_id, week_start=ws_ if version_id is None else None, manager=p.is_manager)
        data = ex.weekly_roster(db, v, ws_, exported_by=p.username)
    except RosterError as exc:
        raise HTTPException(exc.status_code, exc.message)
    return _send(db, p, data, ex.filename("weekly_roster", key=str(ws_), version=v), "weekly_roster",
                 {"week_start": str(ws_), "version_id": v.id}, v.id)


@router.get("/employees.xlsx")
def employees(is_active: bool | None = True, role_pool: RolePool | None = None, db: Session = Depends(get_db),
              p: Principal = Depends(manager_required)):
    data = ex.employee_list(db, exported_by=p.username, is_active=is_active, role_pool=role_pool)
    return _send(db, p, data, ex.filename("employee_list"), "employee_list",
                 {"is_active": is_active, "role_pool": role_pool.value if role_pool else None})


@router.get("/leaves.xlsx")
def leaves(from_date: date | None = None, to_date: date | None = None,
           status: str | None = Query(default=None, pattern="^(Pending|Approved|Rejected|Cancelled)$"),
           employee_id: str | None = Query(default=None, max_length=30),
           leave_type: str | None = Query(default=None, pattern="^(Sick|Casual|Annual)$"),
           db: Session = Depends(get_db), p: Principal = Depends(manager_required)):
    if from_date and to_date and to_date < from_date:
        raise HTTPException(422, "to_date cannot be before from_date")
    data = ex.leave_report(db, exported_by=p.username, from_date=from_date, to_date=to_date, status=status,
                           employee_id=employee_id, leave_type=leave_type)
    key = f"{from_date or 'all'}_{to_date or 'all'}"
    return _send(db, p, data, ex.filename("leave_report", key=key), "leave_report",
                 {"from": str(from_date), "to": str(to_date), "status": status, "employee_id": employee_id})


@router.get("/coverage.xlsx")
def coverage(version_id: int | None = None, db: Session = Depends(get_db), p: Principal = Depends(manager_required)):
    try:
        v = ex.pick_version(db, version_id=version_id, week_start=None, manager=True)
        data = ex.coverage_report(db, v, exported_by=p.username)
    except RosterError as exc:
        raise HTTPException(exc.status_code, exc.message)
    return _send(db, p, data, ex.filename("shift_coverage", key=v.roster_key, version=v), "shift_coverage",
                 {"version_id": v.id}, v.id)
