"""'My' pages: my team (leader, senior agents, members) and my upcoming shifts from the PUBLISHED roster."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_db, get_principal, get_today
from app.models.employee import Employee, RolePool
from app.models.roster import RosterAssignment, RosterVersion

router = APIRouter(prefix="/me", tags=["Me"], dependencies=[Depends(get_principal)])

SHIFT_LABEL = {"M": "Morning", "E": "Evening", "N": "Night", "M-H": "Morning (half duty)", "E-H": "Evening (half duty)",
               "N-H": "Night (half duty)", "R": "Reserve / stand-by", "WO": "Weekly off", "SL": "Sick leave",
               "CL": "Casual leave", "AL": "Annual leave", "-": "No duty"}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def published_codes(db: Session, emp_ids, start: date, end: date) -> tuple[dict[tuple[str, date], str], int | None]:
    """Codes from PUBLISHED rosters only (never drafts). If several published versions cover a day, the newest wins."""
    ids = list(emp_ids)
    if not ids:
        return {}, None
    rows = db.execute(
        select(RosterAssignment.employee_id, RosterAssignment.work_date, RosterAssignment.code, RosterVersion.id)
        .join(RosterVersion, RosterVersion.id == RosterAssignment.version_id)
        .where(RosterVersion.status == "published", RosterAssignment.employee_id.in_(ids),
               RosterAssignment.work_date >= start, RosterAssignment.work_date <= end)
        .order_by(RosterVersion.id)).all()
    out: dict[tuple[str, date], str] = {}
    vid = None
    for e, d, c, v in rows:
        out[(e, d)] = c
        vid = v
    return out, vid


def _person(e: Employee) -> dict:
    return {"employee_id": e.employee_id, "full_name": e.full_name, "role_pool": e.role_pool.value}


def team_members(db: Session, team: str) -> list[Employee]:
    return list(db.scalars(select(Employee).where(Employee.team == team, Employee.is_active.is_(True))
                           .order_by(Employee.employee_id)))


def team_card(db: Session, me: Employee) -> dict:
    """Name, leader, senior agents and members - names/IDs/roles only (no phone, thana, notes)."""
    if not me.team:
        return {"team": None, "leader": None, "seniors": [], "members": [], "size": 0}
    members = team_members(db, me.team)
    leaders = [e for e in members if e.role_pool == RolePool.supervisor]
    return {"team": me.team, "size": len(members),
            "leader": _person(leaders[0]) if leaders else None,
            "leaders": [_person(e) for e in leaders],
            "seniors": [_person(e) for e in members if e.role_pool == RolePool.senior_support],
            "members": [{**_person(e), "is_me": e.employee_id == me.employee_id} for e in members]}


def _me(db: Session, p: Principal) -> Employee:
    e = db.scalar(select(Employee).where(Employee.employee_id == (p.employee_id or "__none__")))
    if not e:
        raise HTTPException(404, "This account is not linked to an employee profile")
    return e


@router.get("/shifts")
def my_shifts(days: int = Query(default=14, ge=1, le=62), db: Session = Depends(get_db), p: Principal = Depends(get_principal),
              today: date = Depends(get_today)):
    """My next shifts from the published roster, starting today."""
    me = _me(db, p)
    end = today + timedelta(days=days - 1)
    codes, vid = published_codes(db, [me.employee_id], today, end)
    items = []
    for k in range(days):
        d = today + timedelta(days=k)
        c = codes.get((me.employee_id, d))
        items.append({"date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()], "code": c, "label": SHIFT_LABEL.get(c, "Not published yet") if c else "Not published yet"})
    nxt = next((i for i in items if i["code"] in ("M", "E", "N", "M-H", "E-H", "N-H")), None)
    return {"employee_id": me.employee_id, "published_version_id": vid, "items": items, "next_duty": nxt}


@router.get("/team")
def my_team(db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    return team_card(db, _me(db, p))


@router.get("/search")
def search_people(q: str = Query(min_length=1, max_length=100), db: Session = Depends(get_db),
                  p: Principal = Depends(get_principal)):
    """Find anybody by name or employee ID and see which team (and leader) they are in. Names / IDs / role / team only."""
    me = _me(db, p)
    pat = f"%{q.strip()}%"
    found = list(db.scalars(select(Employee).where(Employee.is_active.is_(True),
                                                   or_(Employee.full_name.ilike(pat), Employee.employee_id.ilike(pat)))
                            .order_by(Employee.full_name).limit(30)))
    leaders = {e.team: e for e in db.scalars(select(Employee).where(Employee.role_pool == RolePool.supervisor,
                                                                    Employee.is_active.is_(True)))}
    out = []
    for e in found:
        lead = leaders.get(e.team) if e.team else None
        out.append({**_person(e), "team": e.team, "leader": lead.full_name if lead else None,
                    "same_team": bool(me and me.team and e.team == me.team)})
    return out


@router.get("/team/roster")
def my_team_roster(days: int = Query(default=14, ge=1, le=62), team: str | None = None, include_drafts: bool = False,
                   db: Session = Depends(get_db), p: Principal = Depends(get_principal), today: date = Depends(get_today)):
    """The whole team's upcoming shifts (team leaders and managers). Published roster by default."""
    if not p.is_reviewer:
        raise HTTPException(403, "Only team leaders and managers can see the team's roster")
    if p.is_manager and team:
        name = team
    else:
        name = _me(db, p).team
        if not name:
            raise HTTPException(404, "You do not have a team yet")
    members = team_members(db, name)
    end = today + timedelta(days=days - 1)
    codes, vid = published_codes(db, [m.employee_id for m in members], today, end)
    dlist = [today + timedelta(days=k) for k in range(days)]
    return {"team": name, "published_version_id": vid,
            "days": [{"date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()]} for d in dlist],
            "rows": [{**_person(m), "weekly_off_day": m.weekly_off_day.value if m.weekly_off_day else None,
                      "codes": [codes.get((m.employee_id, d)) or "" for d in dlist]} for m in members]}
