"""Seeded portal (200 people, 5 supervisor-named teams): team view, search, private chat, role-based KPI."""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_today
from app.core.config import settings
from app.db.session import Base, get_db
from app.main import app
from tests.test_leave_and_versions import client  # noqa: F401  (fixture used by `sec`)
from tests.test_production import sec  # noqa: F401  (fixture: auth + approval on, users admin/mgr1/...)
from app.models.employee import Employee, RolePool
from app.models.kpi import EmployeeKpi
from app.scripts.seed_team_portal import SUPERVISORS, seed

API = "/api/v1"
TODAY = date(2026, 10, 26)


@pytest.fixture()
def portal(monkeypatch):
    monkeypatch.setattr(settings, "auth_required", True)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    s = Session()
    result = seed(s, TODAY)
    s.close()

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    app.dependency_overrides[get_today] = lambda: TODAY
    c = TestClient(app)
    c.Session, c.seed = Session, result
    yield c
    app.dependency_overrides.clear()
    engine.dispose()


def h(c, user, pw=None):
    r = c.post(f"{API}/auth/login", json={"username": user, "password": pw or f"{user}12345"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_seed_shape_and_names(portal):
    db = portal.Session()
    assert db.scalar(select(func.count()).select_from(Employee)) == 200
    teams = {t for (t,) in db.execute(select(Employee.team).distinct()).all()}
    assert teams == {f"Team {n}" for n in SUPERVISORS}
    for n in SUPERVISORS:
        members = list(db.scalars(select(Employee).where(Employee.team == f"Team {n}")))
        assert len(members) == 40
        assert sum(m.role_pool == RolePool.supervisor for m in members) == 1
        assert sum(m.role_pool == RolePool.senior_support for m in members) == 2
    assert db.scalar(select(Employee.team).where(Employee.employee_id == "EMP002")) == "Team Rahman"
    # re-running is harmless
    again = seed(db, TODAY)
    assert again["new_employees"] == 0 and again["new_accounts"] == 0 and again["kpi_rows_added"] == 0
    db.close()


def test_supervisor_logins_and_roles(portal):
    for n in SUPERVISORS:
        r = portal.post(f"{API}/auth/login", json={"username": n.lower(), "password": f"{n.lower()}12345"})
        assert r.status_code == 200 and r.json()["role"] == "supervisor"
    assert portal.post(f"{API}/auth/login", json={"username": "rahman", "password": "wrong"}).status_code == 401


def test_employee_sees_own_team_and_search_shows_team(portal):
    e = h(portal, "emp002", "emp00212345")
    t = portal.get(f"{API}/me/team", headers=e).json()
    assert t["team"] == "Team Rahman" and t["leader"]["full_name"] == "Rahman" and len(t["members"]) == 40
    assert len(t["seniors"]) == 2
    hits = portal.get(f"{API}/me/search", params={"q": "EMP001"}, headers=e).json()
    assert hits[0]["employee_id"] == "EMP001" and hits[0]["team"] == "Team Arif" and hits[0]["same_team"] is False
    assert hits[0]["leader"] == "Arif"
    mate = [m for m in t["members"] if not m["is_me"]][0]
    by_name = portal.get(f"{API}/me/search", params={"q": mate["full_name"]}, headers=e).json()
    assert any(x["employee_id"] == mate["employee_id"] and x["same_team"] for x in by_name)
    assert all(set(x) == {"employee_id", "full_name", "role_pool", "team", "leader", "same_team"} for x in by_name)


def test_chat_only_assigned_supervisor(portal):
    e = h(portal, "emp002", "emp00212345")
    assert portal.post(f"{API}/messages/thread/EMP002", headers=e, json={"text": "Need a shift change"}).status_code == 201
    rahman, arif = h(portal, "rahman"), h(portal, "arif")
    th = portal.get(f"{API}/messages/threads", headers=rahman).json()
    assert len(th) == 39 and next(x for x in th if x["employee_id"] == "EMP002")["unread"] == 1  # members, not the leader
    assert portal.get(f"{API}/messages/thread/EMP002", headers=rahman).json()["messages"][0]["text"] == "Need a shift change"
    assert portal.get(f"{API}/messages/thread/EMP002", headers=arif).status_code == 403          # another team's supervisor
    assert portal.get(f"{API}/messages/thread/EMP002", headers=h(portal, "emp001", "emp00112345")).status_code == 403
    assert portal.post(f"{API}/messages/thread/EMP002", headers=arif, json={"text": "hi"}).status_code == 403
    # admins / managers do not read private chats either
    s = portal.Session()
    from app.core.security import hash_password
    from app.models.user import AppUser
    s.add_all([AppUser(username="adm", password_hash=hash_password("Passw0rd!x"), role="admin"),
               AppUser(username="mgr", password_hash=hash_password("Passw0rd!x"), role="manager")])
    s.commit(); s.close()
    for u in ("adm", "mgr"):
        hh = h(portal, u, "Passw0rd!x")
        assert portal.get(f"{API}/messages/thread/EMP002", headers=hh).status_code == 403
        assert portal.get(f"{API}/messages/threads", headers=hh).json() == []


def test_employee_sees_only_own_kpi(portal):
    e = h(portal, "emp002", "emp00212345")
    k = portal.get(f"{API}/kpi/me", headers=e).json()
    assert k["employee_id"] == "EMP002" and len(k["items"]) >= 2 and all(i["employee_id"] == "EMP002" for i in k["items"])
    assert k["can_upload"] is False
    for path in ("/kpi/team?team=Team Rahman", "/kpi/overview", "/kpi/scope"):
        r = portal.get(f"{API}{path}", headers=e)
        assert (r.status_code == 403) or (path == "/kpi/scope" and r.json()["people"] == []), path
    assert portal.put(f"{API}/kpi/EMP002/2026-10", headers=e, json={"score": 100}).status_code == 403   # cannot edit own KPI
    assert portal.put(f"{API}/kpi/EMP001/2026-10", headers=e, json={"score": 100}).status_code == 403


def test_supervisor_uploads_for_own_team_only(portal):
    rahman = h(portal, "rahman")
    r = portal.put(f"{API}/kpi/EMP002/2026-10", headers=rahman, json={"quality": 90, "attendance": 100, "productivity": 80, "csat": 90, "remarks": "great"})
    assert r.status_code == 200 and r.json()["score"] == 90.0 and r.json()["uploaded_by"] == "Rahman"
    assert portal.put(f"{API}/kpi/EMP001/2026-10", headers=rahman, json={"score": 50}).status_code == 403      # Arif's team
    assert portal.put(f"{API}/kpi/EMP002/2026-11", headers=rahman, json={"score": 50}).status_code == 422      # future month
    assert portal.put(f"{API}/kpi/EMP002/2026-10", headers=rahman, json={}).status_code == 422                 # nothing given
    assert portal.put(f"{API}/kpi/EMP002/2026-10", headers=rahman, json={"score": 101}).status_code == 422
    assert portal.put(f"{API}/kpi/EMP200/2026-10", headers=rahman, json={"score": 50}).status_code == 403      # a supervisor's own KPI
    me = portal.get(f"{API}/kpi/me", headers=h(portal, "emp002", "emp00212345")).json()
    assert me["latest"]["period"] == "2026-10" and me["latest"]["score"] == 90.0
    # bulk: mixed good / foreign / duplicate rows
    b = portal.post(f"{API}/kpi/bulk", headers=rahman, json={"period": "2026-09", "rows": [
        {"employee_id": "emp002", "score": 70}, {"employee_id": "EMP001", "score": 70}, {"employee_id": "EMP002", "score": 71},
        {"employee_id": "EMP007", "quality": 88}]}).json()
    assert b["updated"] + b["created"] == 2 and b["rejected"] == 2
    assert portal.delete(f"{API}/kpi/EMP002/2026-10", headers=rahman).status_code == 204


def test_employees_including_seniors_cannot_upload_kpi(portal):
    db = portal.Session()
    senior = db.scalar(select(Employee).where(Employee.employee_id == "EMP006"))
    assert senior.role_pool == RolePool.senior_support and senior.team == "Team Arif"
    db.close()
    for user, pw in (("emp006", "emp00612345"), ("emp001", "emp00112345")):   # a senior agent and a plain agent
        e = h(portal, user, pw)
        assert portal.get(f"{API}/kpi/scope", headers=e).json()["people"] == []
        assert portal.put(f"{API}/kpi/EMP001/2026-10", headers=e, json={"score": 77}).status_code == 403
        assert portal.post(f"{API}/kpi/bulk", headers=e, json={"period": "2026-10", "rows": [{"employee_id": "EMP001", "score": 77}]}).status_code == 403
        assert portal.get(f"{API}/kpi/me", headers=e).json()["can_upload"] is False
        assert portal.get(f"{API}/kpi/team?team=Team Arif", headers=e).status_code == 403
    assert portal.put(f"{API}/kpi/EMP001/2026-10", headers=h(portal, "arif"), json={"score": 77}).status_code == 200   # the leader still can


def test_numbered_teams_are_renamed_after_their_leader(portal):
    db = portal.Session()
    for e in db.scalars(select(Employee).where(Employee.team.is_not(None))):
        e.team = {"Team Arif": "Team 1", "Team Rahman": "Team 2", "Team Miraz": "Team 3", "Team Nusrat": "Team 4", "Team Ziarul": "Team 5"}[e.team]
    db.commit()
    db.close()
    from app.core.security import hash_password
    from app.models.user import AppUser
    db = portal.Session()
    db.add(AppUser(username="boss", password_hash=hash_password("Passw0rd!x"), role="manager"))
    db.commit()
    db.close()
    assert portal.post(f"{API}/teams/rename-to-leaders", headers=h(portal, "arif")).status_code == 403   # leaders cannot, managers can
    r = portal.post(f"{API}/teams/rename-to-leaders", headers=h(portal, "boss", "Passw0rd!x")).json()
    assert sorted(r["renamed"].values()) == ["Team Arif", "Team Miraz", "Team Nusrat", "Team Rahman", "Team Ziarul"]
    assert r["still_numbered"] == [] and all(t["size"] == 40 for t in r["teams"])


def test_team_performance_and_overview(portal):
    rahman = h(portal, "rahman")
    t = portal.get(f"{API}/kpi/team", params={"period": "2026-09"}, headers=rahman).json()
    assert t["team"] == "Team Rahman" and t["members"] == 39 and t["reported"] == 39 and 40 < t["average"] <= 100
    assert len(t["trend"]) == 6 and t["rows"][0]["kpi"]["score"] >= t["rows"][-1]["kpi"]["score"]
    assert portal.get(f"{API}/kpi/team", params={"team": "Team Arif"}, headers=rahman).status_code == 403
    ov = portal.get(f"{API}/kpi/overview", params={"period": "2026-09"}, headers=rahman).json()
    assert len(ov["teams"]) == 5 and [x["rank"] for x in ov["teams"]] == [1, 2, 3, 4, 5]
    assert sum(x["is_mine"] for x in ov["teams"]) == 1
    assert all(set(x) >= {"team", "leader", "average"} and "rows" not in x for x in ov["teams"])
    assert portal.get(f"{API}/kpi/overview", headers=h(portal, "emp002", "emp00212345")).status_code == 403


# ------------------------------------------------ credentials CSV / team naming --

def test_bulk_accounts_from_credentials_csv(sec):
    from tests.test_production import API, PW, hdr
    adm = hdr(sec, "admin")
    rows = [
        {"username": "arif", "password": "arif12345", "role": "supervisor", "employee_id": "EMP196", "name": "Arif", "team": "Team Arif"},
        {"username": "emp001", "password": "emp00112345", "role": "employee", "employee_id": "EMP001", "name": "Dolly Bhuiyan", "team": "Team Arif"},
        {"username": "bad1", "password": "short", "role": "employee", "employee_id": "EMP002", "name": "X"},
        {"username": "bad2", "password": "longenough1", "role": "employee"},
        {"username": "emp001", "password": "emp00112345", "role": "employee", "employee_id": "EMP001"},
    ]
    r = sec.post(f"{API}/auth/users/bulk", json={"rows": rows}, headers=adm)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["created"] == 2 and d["profiles_created"] == 2 and d["rejected"] == 3
    assert {e["username"] for e in d["errors"]} == {"bad1", "bad2", "emp001"}
    assert sec.post(f"{API}/auth/login", json={"username": "emp001", "password": "emp00112345"}).status_code == 200
    assert sec.post(f"{API}/auth/login", json={"username": "arif", "password": "arif12345"}).status_code == 200
    # a broken account is repaired by running it again with the right password; "(unchanged)" keeps the old one
    sec.post(f"{API}/auth/users/bulk", json={"rows": [{"username": "emp001", "password": "NewPass#123", "role": "employee", "employee_id": "EMP001"}]}, headers=adm)
    assert sec.post(f"{API}/auth/login", json={"username": "emp001", "password": "emp00112345"}).status_code == 401
    sec.post(f"{API}/auth/users/bulk", json={"rows": [{"username": "emp001", "password": "(unchanged)", "role": "employee", "employee_id": "EMP001"}]}, headers=adm)
    assert sec.post(f"{API}/auth/login", json={"username": "emp001", "password": "NewPass#123"}).status_code == 200
    assert sec.post(f"{API}/auth/users/bulk", json={"rows": rows[:1]}, headers=hdr(sec, "mgr1")).status_code == 403  # admin only


def test_teams_are_always_named_after_a_leader(sec):
    from app.models.employee import Employee, RolePool
    from tests.test_production import API, hdr
    mgr = hdr(sec, "mgr1")
    s = sec.Session()
    for n in ("Arif", "Rahman", "Miraz"):
        s.add(Employee(employee_id=f"L{n}", full_name=n, role_pool=RolePool.supervisor))
    s.commit()
    s.close()
    r = sec.post(f"{API}/teams/auto-assign?teams=5", headers=mgr).json()  # 5 requested, 3 leaders -> 3 teams, no "Team 4"
    assert sorted(t["team"] for t in r["teams"]) == ["Team Arif", "Team Miraz", "Team Rahman"]
    assert any("3 team" in w for w in r["warnings"])
    s = sec.Session()
    s.query(Employee).filter(Employee.role_pool == RolePool.supervisor).update({"role_pool": RolePool.general})
    s.commit()
    s.close()
    assert sec.post(f"{API}/teams/auto-assign", headers=mgr).status_code == 409  # no leader at all
