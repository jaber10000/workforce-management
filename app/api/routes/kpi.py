"""Monthly KPI.

* Everyone sees only their OWN monthly KPI (`/kpi/me`).
* A supervisor uploads KPI for the people of their own team (single or bulk) and sees the team's performance.
* Only team leaders (supervisors) and managers/admins can upload or edit KPI. Employees, including senior agents, cannot.
* Supervisors, managers and admins see how the teams compare ("team leader performance" = the team's average).
"""
import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_db, get_principal, get_today
from app.models.employee import Employee, RolePool
from app.models.kpi import EmployeeKpi
from app.services import audit

router = APIRouter(prefix="/kpi", tags=["KPI"], dependencies=[Depends(get_principal)])

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
METRICS = ("quality", "attendance", "productivity", "csat")


class KpiIn(BaseModel):
    score: float | None = Field(default=None, ge=0, le=100)
    quality: float | None = Field(default=None, ge=0, le=100)
    attendance: float | None = Field(default=None, ge=0, le=100)
    productivity: float | None = Field(default=None, ge=0, le=100)
    csat: float | None = Field(default=None, ge=0, le=100)
    remarks: str | None = Field(default=None, max_length=500)


class BulkRow(KpiIn):
    employee_id: str = Field(min_length=1, max_length=30)


class BulkIn(BaseModel):
    period: str
    rows: list[BulkRow] = Field(min_length=1, max_length=500)


# ------------------------------------------------------------------ helpers --

def _period(period: str | None, today: date) -> str:
    if period is None:
        return f"{today.year:04d}-{today.month:02d}"
    if not PERIOD_RE.match(period):
        raise HTTPException(422, "period must look like 2026-10")
    return period


def _check_not_future(period: str, today: date) -> None:
    if period > f"{today.year:04d}-{today.month:02d}":
        raise HTTPException(422, "KPI cannot be uploaded for a future month")


def _me(db: Session, p: Principal) -> Employee | None:
    return db.scalar(select(Employee).where(Employee.employee_id == (p.employee_id or "__none__")))


def _team_members(db: Session, team: str | None) -> list[Employee]:
    if not team:
        return []
    return list(db.scalars(select(Employee).where(Employee.team == team, Employee.is_active.is_(True))
                           .order_by(Employee.employee_id)))


def upload_scope(db: Session, p: Principal) -> list[Employee]:
    """The people this account may upload KPI for (empty = not allowed)."""
    if p.is_manager:
        return list(db.scalars(select(Employee).where(Employee.is_active.is_(True),
                                                      Employee.role_pool != RolePool.supervisor).order_by(Employee.employee_id)))
    me = _me(db, p)
    if not me or not me.team:
        return []
    if p.role == "supervisor":
        return [e for e in _team_members(db, me.team) if e.employee_id != me.employee_id and e.role_pool != RolePool.supervisor]
    return []


def _out(k: EmployeeKpi) -> dict:
    return {"employee_id": k.employee_id, "period": k.period, "score": round(k.score, 1), "quality": k.quality,
            "attendance": k.attendance, "productivity": k.productivity, "csat": k.csat, "remarks": k.remarks,
            "uploaded_by": k.uploaded_by_name,
            "updated_at": (k.updated_at or k.created_at).isoformat() if (k.updated_at or k.created_at) else None}


def _score(data: KpiIn) -> float:
    if data.score is not None:
        return data.score
    vals = [getattr(data, m) for m in METRICS if getattr(data, m) is not None]
    if not vals:
        raise HTTPException(422, "Give the overall score or at least one metric (quality, attendance, productivity, csat)")
    return round(sum(vals) / len(vals), 1)


def _upsert(db: Session, p: Principal, uploader: str, emp: Employee, period: str, data: KpiIn) -> str:
    score = _score(data)
    row = db.scalar(select(EmployeeKpi).where(EmployeeKpi.employee_id == emp.employee_id, EmployeeKpi.period == period))
    fields = {"score": score, "quality": data.quality, "attendance": data.attendance, "productivity": data.productivity,
              "csat": data.csat, "remarks": (data.remarks or "").strip() or None,
              "uploaded_by": p.username, "uploaded_by_name": uploader}
    if row:
        for k, v in fields.items():
            setattr(row, k, v)
        action = "updated"
    else:
        db.add(EmployeeKpi(employee_id=emp.employee_id, period=period, **fields))
        action = "created"
    audit.log(db, f"kpi_{action}", "kpi", f"{emp.employee_id}:{period}", {"score": score}, actor=p.username)
    return action


def _uploader_name(db: Session, p: Principal) -> str:
    me = _me(db, p)
    return me.full_name if me else p.username


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def team_stats(db: Session, team: str, period: str) -> dict:
    members = [m for m in _team_members(db, team)]
    agents = [m for m in members if m.role_pool != RolePool.supervisor]
    ids = [m.employee_id for m in agents]
    rows = {k.employee_id: k for k in db.scalars(select(EmployeeKpi).where(EmployeeKpi.employee_id.in_(ids), EmployeeKpi.period == period))} if ids else {}
    scores = [r.score for r in rows.values()]
    leader = next((m for m in members if m.role_pool == RolePool.supervisor), None)
    return {"team": team, "leader": {"employee_id": leader.employee_id, "full_name": leader.full_name} if leader else None,
            "members": len(agents), "reported": len(rows), "average": _avg(scores),
            "best": round(max(scores), 1) if scores else None, "lowest": round(min(scores), 1) if scores else None,
            "metrics": {m: _avg([getattr(r, m) for r in rows.values() if getattr(r, m) is not None]) for m in METRICS}}


def _last_periods(period: str, n: int) -> list[str]:
    y, m = int(period[:4]), int(period[5:])
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


# ---------------------------------------------------------------- endpoints --

@router.get("/me")
def my_kpi(months: int = Query(default=12, ge=1, le=36), db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    """My own monthly KPI, newest last. Nobody else's KPI is ever returned here."""
    me = _me(db, p)
    if not me:
        raise HTTPException(404, "This account is not linked to an employee profile")
    rows = list(db.scalars(select(EmployeeKpi).where(EmployeeKpi.employee_id == me.employee_id)
                           .order_by(EmployeeKpi.period.desc()).limit(months)))[::-1]
    items = [_out(r) for r in rows]
    latest = items[-1] if items else None
    prev = items[-2] if len(items) > 1 else None
    return {"employee_id": me.employee_id, "full_name": me.full_name, "team": me.team, "items": items, "latest": latest,
            "change": round(latest["score"] - prev["score"], 1) if latest and prev else None,
            "is_team_leader": me.role_pool == RolePool.supervisor,
            "can_upload": bool(upload_scope(db, p))}


@router.get("/scope")
def scope(period: str | None = None, db: Session = Depends(get_db), p: Principal = Depends(get_principal),
          today: date = Depends(get_today)):
    """People I may upload KPI for, with what is already saved for the month (so the form can show and edit it)."""
    period = _period(period, today)
    people = upload_scope(db, p)
    ids = [e.employee_id for e in people]
    saved = {k.employee_id: k for k in db.scalars(select(EmployeeKpi).where(EmployeeKpi.employee_id.in_(ids), EmployeeKpi.period == period))} if ids else {}
    return {"period": period, "people": [{"employee_id": e.employee_id, "full_name": e.full_name, "role_pool": e.role_pool.value,
                                          "team": e.team, "kpi": _out(saved[e.employee_id]) if e.employee_id in saved else None}
                                         for e in people]}


@router.put("/{employee_id}/{period}")
def upload_one(employee_id: str, period: str, body: KpiIn, db: Session = Depends(get_db), p: Principal = Depends(get_principal),
               today: date = Depends(get_today)):
    period = _period(period, today)
    _check_not_future(period, today)
    emp = next((e for e in upload_scope(db, p) if e.employee_id == employee_id), None)
    if not emp:
        raise HTTPException(403, "You can only upload KPI for the people of your own team that you are responsible for")
    action = _upsert(db, p, _uploader_name(db, p), emp, period, body)
    db.commit()
    row = db.scalar(select(EmployeeKpi).where(EmployeeKpi.employee_id == employee_id, EmployeeKpi.period == period))
    return {"action": action, **_out(row)}


@router.post("/bulk")
def upload_bulk(body: BulkIn, db: Session = Depends(get_db), p: Principal = Depends(get_principal), today: date = Depends(get_today)):
    """Upload many rows at once (CSV in the UI). Rows outside your scope or invalid are reported, never saved."""
    period = _period(body.period, today)
    _check_not_future(period, today)
    scope_by_id = {e.employee_id.lower(): e for e in upload_scope(db, p)}
    if not scope_by_id:
        raise HTTPException(403, "You are not allowed to upload KPI")
    who = _uploader_name(db, p)
    created = updated = 0
    errors: list[dict] = []
    seen: set[str] = set()
    for i, row in enumerate(body.rows, start=1):
        emp = scope_by_id.get(row.employee_id.strip().lower())
        if not emp:
            errors.append({"row": i, "employee_id": row.employee_id, "error": "not in your team / not allowed"})
            continue
        if emp.employee_id in seen:
            errors.append({"row": i, "employee_id": row.employee_id, "error": "listed twice"})
            continue
        seen.add(emp.employee_id)
        try:
            action = _upsert(db, p, who, emp, period, row)
        except HTTPException as e:
            errors.append({"row": i, "employee_id": row.employee_id, "error": e.detail})
            continue
        created += action == "created"
        updated += action == "updated"
    db.commit()
    return {"period": period, "created": created, "updated": updated, "rejected": len(errors), "errors": errors}


@router.delete("/{employee_id}/{period}", status_code=204)
def delete_one(employee_id: str, period: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal),
               today: date = Depends(get_today)):
    period = _period(period, today)
    if not any(e.employee_id == employee_id for e in upload_scope(db, p)):
        raise HTTPException(403, "You can only remove KPI for your own team")
    row = db.scalar(select(EmployeeKpi).where(EmployeeKpi.employee_id == employee_id, EmployeeKpi.period == period))
    if not row:
        raise HTTPException(404, "No KPI saved for that month")
    db.delete(row)
    audit.log(db, "kpi_deleted", "kpi", f"{employee_id}:{period}", {}, actor=p.username)
    db.commit()


@router.get("/team")
def team_performance(period: str | None = None, team: str | None = None, db: Session = Depends(get_db),
                     p: Principal = Depends(get_principal), today: date = Depends(get_today)):
    """Team performance for one month plus the last six months' trend. Supervisor: own team only.
    Manager/admin: any team (`team=`). Employees (incl. seniors): not allowed, they see only their own KPI."""
    if not p.is_reviewer:
        raise HTTPException(403, "Only team leaders and managers can see team performance")
    period = _period(period, today)
    if p.is_manager:
        name = team
        if not name:
            raise HTTPException(422, "team is required")
    else:
        me = _me(db, p)
        name = me.team if me else None
        if not name or (team and team != name):
            raise HTTPException(403, "You can only see your own team's performance")
    members = _team_members(db, name)
    if not members:
        raise HTTPException(404, "Team not found")
    agents = [m for m in members if m.role_pool != RolePool.supervisor]
    ids = [m.employee_id for m in agents]
    periods = _last_periods(period, 6)
    allrows = list(db.scalars(select(EmployeeKpi).where(EmployeeKpi.employee_id.in_(ids), EmployeeKpi.period.in_(periods)))) if ids else []
    cur = {k.employee_id: k for k in allrows if k.period == period}
    prev_p = _last_periods(period, 2)[0]
    prev = {k.employee_id: k for k in allrows if k.period == prev_p}
    rows = []
    for m in agents:
        k = cur.get(m.employee_id)
        pk = prev.get(m.employee_id)
        rows.append({"employee_id": m.employee_id, "full_name": m.full_name, "role_pool": m.role_pool.value,
                     "kpi": _out(k) if k else None, "change": round(k.score - pk.score, 1) if k and pk else None})
    rows.sort(key=lambda r: (r["kpi"] is None, -(r["kpi"]["score"] if r["kpi"] else 0), r["full_name"]))
    trend = [{"period": per, "average": _avg([k.score for k in allrows if k.period == per]),
              "reported": sum(1 for k in allrows if k.period == per)} for per in periods]
    return {**team_stats(db, name, period), "period": period, "rows": rows, "trend": trend}


@router.get("/overview")
def overview(period: str | None = None, db: Session = Depends(get_db), p: Principal = Depends(get_principal),
             today: date = Depends(get_today)):
    """All teams side by side, best first (a team leader's performance = their team's average).
    Aggregates only: no individual KPI of other teams is exposed here."""
    if not p.is_reviewer:
        raise HTTPException(403, "Only team leaders and managers can compare teams")
    period = _period(period, today)
    names = [t for (t,) in db.execute(select(Employee.team).where(Employee.team.is_not(None), Employee.is_active.is_(True)).distinct()).all()]
    mine = None
    if p.role == "supervisor":
        me = _me(db, p)
        mine = me.team if me else None
    teams = [team_stats(db, n, period) for n in sorted(names)]
    for t in teams:
        t["is_mine"] = t["team"] == mine
    teams.sort(key=lambda t: (t["average"] is None, -(t["average"] or 0), t["team"]))
    for i, t in enumerate(teams, start=1):
        t["rank"] = i if t["average"] is not None else None
    return {"period": period, "teams": teams}
