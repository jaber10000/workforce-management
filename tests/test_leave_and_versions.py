"""Leave rules, auto roster adjustment, versioning, audit log and published-roster protection.
Uses a small synthetic workforce so each solve takes a couple of seconds."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db, get_today
from app.db.session import Base
from app.main import app
from app.models.roster import RosterAssignment
from tests.helpers import START, seed_small

TODAY = date(2026, 10, 30)  # mid-window: Oct 26..29 are "past"
Q = {"time_limit_seconds": 6}


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    s = Session()
    seed_small(s)
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
    c.Session = Session
    yield c
    app.dependency_overrides.clear()
    engine.dispose()


def gen(client, **extra):
    r = client.post("/api/v1/roster/generate", json={"start_date": str(START), "days": 14, **Q, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def cells(client, vid):
    g = client.get(f"/api/v1/roster/versions/{vid}").json()["grid"]
    return {r["employee_id"]: r["codes"] for r in g["rows"]}


# ------------------------------------------------------------------ leave --

def test_apply_rules_overlap_half_day_and_balance(client):
    ok = client.post("/api/v1/leaves", json={
        "employee_id": "T001", "leave_type": "Casual", "start_date": "2026-11-02", "end_date": "2026-11-02",
        "half_day": True, "reason": "x"})
    assert ok.status_code == 201 and ok.json()["days"] == 0.5 and ok.json()["status"] == "Pending"
    base = {"employee_id": "T001", "leave_type": "Casual", "start_date": "2026-11-02", "end_date": "2026-11-03"}
    assert client.post("/api/v1/leaves", json=base).status_code == 409  # overlap
    annual_half = {**base, "leave_type": "Annual", "end_date": "2026-11-09", "half_day": True}
    assert client.post("/api/v1/leaves", json=annual_half).status_code == 422  # half-day not allowed for Annual
    multi_half = {**base, "leave_type": "Sick", "half_day": True}
    assert client.post("/api/v1/leaves", json=multi_half).status_code == 422  # half day must be 1 day
    too_long = {"employee_id": "T002", "leave_type": "Casual", "start_date": "2026-11-01", "end_date": "2026-11-15"}
    r = client.post("/api/v1/leaves", json=too_long)  # 15 days > 10 casual
    assert r.status_code == 409 and "Insufficient" in r.json()["detail"]
    assert client.post("/api/v1/leaves", json={**base, "employee_id": "NOPE"}).status_code == 404
    bal = {b["leave_type"]: b for b in client.get("/api/v1/leaves/balance/T001").json()}
    assert bal["Casual"]["pending"] == 0.5 and bal["Casual"]["available"] == 9.5
    assert bal["Annual"]["total"] == 20 and bal["Sick"]["total"] == 14


def test_approve_reject_cancel_flow_and_balance(client):
    r = client.post("/api/v1/leaves", json={"employee_id": "T003", "leave_type": "Sick",
                                            "start_date": "2026-11-04", "end_date": "2026-11-05"})
    app_id = r.json()["application_id"]
    res = client.post(f"/api/v1/leaves/{app_id}/approve", json={"auto_roster": False})
    assert res.status_code == 200 and res.json()["leave"]["status"] == "Approved"
    assert client.post(f"/api/v1/leaves/{app_id}/approve", json={"auto_roster": False}).status_code == 409
    bal = {b["leave_type"]: b for b in client.get("/api/v1/leaves/balance/T003").json()}
    assert bal["Sick"]["used"] == 2 and bal["Sick"]["remaining"] == 12
    r2 = client.post("/api/v1/leaves", json={"employee_id": "T004", "leave_type": "Sick",
                                             "start_date": "2026-11-04", "end_date": "2026-11-04"})
    assert client.post(f"/api/v1/leaves/{r2.json()['application_id']}/reject", json={"note": "busy"}).json()["status"] == "Rejected"
    assert client.post(f"/api/v1/leaves/{app_id}/cancel", json={"auto_roster": False}).json()["leave"]["status"] == "Cancelled"
    bal = {b["leave_type"]: b for b in client.get("/api/v1/leaves/balance/T003").json()}
    assert bal["Sick"]["used"] == 0


def test_annual_carry_forward_is_capped(client):
    s = client.Session()
    from app.services import leave_service
    from app.models.leave import LeaveApplication
    leave_service.ensure_balance(s, "T005", 2026, "Annual")
    s.add(LeaveApplication(application_id="LV9001", employee_id="T005", leave_type="Annual",
                           start_date=date(2026, 3, 1), end_date=date(2026, 3, 4), days=4, status="Approved"))
    s.commit()
    bal = {b["leave_type"]: b for b in leave_service.get_balances(s, "T005", 2027)}
    assert bal["Annual"]["carried_forward"] == 10 and bal["Annual"]["total"] == 30  # 16 left, capped at 10
    assert bal["Casual"]["carried_forward"] == 0  # casual does not carry forward


# ---------------------------------------------------- versioning / audit --

def test_generate_creates_versions_and_audit(client):
    v1 = gen(client)
    v2 = gen(client)
    assert (v1["version_no"], v2["version_no"]) == (1, 2) and v1["roster_key"] == v2["roster_key"]
    assert v1["status"] == "draft" and v1["summary"]["shortage"]["total"] == 0
    vers = client.get("/api/v1/roster/versions").json()
    assert [v["id"] for v in vers] == [v2["id"], v1["id"]]
    log = client.get("/api/v1/roster/audit-log", params={"action": "roster_generated"}).json()
    assert len(log) == 2 and log[0]["details"]["version_no"] == 2


def test_published_version_is_immutable_and_reoptimise_creates_new_version(client):
    v1 = gen(client)
    before = cells(client, v1["id"])
    pub = client.post(f"/api/v1/roster/versions/{v1['id']}/publish")
    assert pub.status_code == 200 and pub.json()["status"] == "published"
    assert client.post(f"/api/v1/roster/versions/{v1['id']}/publish").status_code == 409
    edit = {"employee_id": "T001", "work_date": "2026-11-05", "code": "R", "reason": "test change"}
    assert client.put(f"/api/v1/roster/versions/{v1['id']}/assignments", json=edit).status_code == 409
    assert client.delete(f"/api/v1/roster/versions/{v1['id']}").status_code == 409

    r = client.post("/api/v1/roster/regenerate", json={"base_version_id": v1["id"], "from_date": "2026-10-27", "reason": "late change", **Q})
    assert r.status_code == 201, r.text
    v2 = r.json()
    assert v2["version_no"] == 2 and v2["base_version_id"] == v1["id"]
    assert v2["lock_before"] == str(TODAY)  # published history (before today) forced locked
    after = cells(client, v2["id"])
    i_today = (TODAY - START).days
    for emp, codes in before.items():
        assert after[emp][:i_today] == codes[:i_today], f"{emp} history changed"
    assert cells(client, v1["id"]) == before  # original version untouched


def test_leave_approval_syncs_roster_with_minimal_changes(client):
    v1 = gen(client)
    client.post(f"/api/v1/roster/versions/{v1['id']}/publish")
    codes = cells(client, v1["id"])
    d = date(2026, 11, 4)
    idx = (d - START).days
    emp = next(e for e, c in codes.items() if c[idx] in ("M", "E", "N"))  # someone who works that day
    lv = client.post("/api/v1/leaves", json={"employee_id": emp, "leave_type": "Casual",
                                             "start_date": str(d), "end_date": str(d)}).json()
    res = client.post(f"/api/v1/leaves/{lv['application_id']}/approve", json={"decided_by": "hr"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["roster_adjustment"] == "new draft version created"
    v2 = body["roster_version"]
    assert v2["trigger"] == "leave_approved" and v2["base_version_id"] == v1["id"] and v2["status"] == "draft"
    new = cells(client, v2["id"])
    assert new[emp][idx] == "CL"
    assert v2["summary"]["shortage"]["total"] == 0  # replacement found
    diff = client.get(f"/api/v1/roster/versions/{v2['id']}/diff").json()["changes"]
    assert 1 <= len(diff) <= 12, f"too many changes for one leave: {len(diff)}"
    assert all(date.fromisoformat(c["date"]) >= TODAY for c in diff)
    assert client.get(f"/api/v1/roster/versions/{v1['id']}").json()["version"]["status"] == "published"
    actions = {a["action"] for a in client.get("/api/v1/roster/audit-log").json()}
    assert {"leave_applied", "leave_approved", "roster_generated", "roster_published", "roster_regenerated"} <= actions


def test_leave_in_the_past_does_not_touch_published_roster(client):
    v1 = gen(client)
    client.post(f"/api/v1/roster/versions/{v1['id']}/publish")
    lv = client.post("/api/v1/leaves", json={"employee_id": "T010", "leave_type": "Sick",
                                             "start_date": "2026-10-27", "end_date": "2026-10-27"}).json()
    res = client.post(f"/api/v1/leaves/{lv['application_id']}/approve").json()
    assert res["roster_version"] is None and "no roster change needed" in res["roster_adjustment"]
    assert len(client.get("/api/v1/roster/versions").json()) == 1


def test_new_employee_triggers_roster_update(client):
    v1 = gen(client)
    r = client.post("/api/v1/employees", json={"employee_id": "NEW001", "full_name": "New Joiner",
                                               "joining_date": "2026-11-02", "weekly_off_day": "Sunday",
                                               "is_shift_eligible_night": True})
    assert r.status_code == 201
    vers = client.get("/api/v1/roster/versions").json()
    assert len(vers) == 2 and vers[0]["trigger"] == "employee_added"
    new = cells(client, vers[0]["id"])
    assert "NEW001" in new
    assert all(c == "-" for c in new["NEW001"][:7])  # before joining date
    assert vers[0]["summary"]["shortage"]["total"] == 0


def test_shortage_report_and_publish_guard(client):
    r = client.post("/api/v1/roster/generate", json={
        "start_date": str(START), "days": 7, **Q,
        "requirements": [{"work_date": str(START + timedelta(days=k)), "morning_required": 14, "evening_required": 10,
                          "night_required": 30, "min_senior": 1} for k in range(7)]})
    v = r.json()
    assert v["summary"]["shortage"]["night"] > 0 and v["summary"]["days_with_shortage"] > 0
    cov = client.get(f"/api/v1/roster/versions/{v['id']}/coverage").json()
    assert cov["has_shortage"] and cov["days"][0]["shifts"]["night"]["shortage"] > 0
    assert client.post(f"/api/v1/roster/versions/{v['id']}/publish").status_code == 409
    ok = client.post(f"/api/v1/roster/versions/{v['id']}/publish", json={"acknowledge_shortage": True})
    assert ok.status_code == 200


def test_draft_cell_edit_updates_coverage_and_export(client):
    v = gen(client)
    codes = cells(client, v["id"])
    emp = next(e for e, c in codes.items() if c[7] == "M")
    r = client.put(f"/api/v1/roster/versions/{v['id']}/assignments",
                   json={"employee_id": emp, "work_date": "2026-11-02", "code": "R", "reason": "test change"})
    assert r.status_code == 200
    cov = client.get(f"/api/v1/roster/versions/{v['id']}/coverage").json()
    assert cov["days"][7]["shifts"]["morning"]["shortage"] > 0  # a half-duty day can leave 0.5, so not >= 1
    bad = client.put(f"/api/v1/roster/versions/{v['id']}/assignments",
                     json={"employee_id": emp, "work_date": "2026-11-02", "code": "ZZ", "reason": "test change"})
    assert bad.status_code == 422
    x = client.get(f"/api/v1/roster/versions/{v['id']}/export.xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_fairness_report_shape(client):
    v = gen(client)
    f = client.get(f"/api/v1/roster/versions/{v['id']}/fairness").json()
    assert f["summary"]["night_pool"] > 0 and f["summary"]["night_spread"] <= 3
    assert all(r["max_consecutive_nights"] <= 3 for r in f["employees"])
