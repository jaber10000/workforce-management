"""Leave management: preview, roster impact / replacement proposals, long-leave off-day re-plan.
Uses the small synthetic workforce from helpers (70 employees, 14 days)."""
from datetime import date

from sqlalchemy import select

from app.models.leave import LeaveApplication, OffDayPlan
from app.services.roster_engine import EmpIn
from tests.helpers import DAYS, START
from tests.test_leave_and_versions import Q, TODAY, client, cells, gen  # noqa: F401  (client is a fixture)

API = "/api/v1"


def apply(client, emp, kind, start, end, **extra):
    r = client.post(f"{API}/leaves", json={"employee_id": emp, "leave_type": kind, "start_date": start,
                                           "end_date": end, **extra})
    assert r.status_code == 201, r.text
    return r.json()["application_id"]


def working_emp(client, vid, d):
    idx = (d - START).days
    return next(e for e, c in cells(client, vid).items() if c[idx] in ("M", "E", "N"))


def plans(client):
    s = client.Session()
    try:
        return list(s.scalars(select(OffDayPlan)))
    finally:
        s.close()


# ---------------------------------------------------------------- preview --

def test_preview_shows_impact_and_saves_nothing(client):
    v1 = gen(client)
    d = date(2026, 11, 4)
    emp = working_emp(client, v1["id"], d)
    lid = apply(client, emp, "Casual", str(d), str(d))
    before_codes = cells(client, v1["id"])

    r = client.post(f"{API}/leaves/{lid}/preview", params={"time_limit_seconds": 6})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["simulated"] is True and "roster_version" not in body
    imp = body["impact"]
    assert [x["date"] for x in imp["removed_assignments"]] == [str(d)]
    assert imp["shortage_total_after"] == 0 and imp["replacements"], "someone must cover the removed duty"
    assert all(x["employee_id"] != emp for x in imp["replacements"])

    # nothing persisted
    assert client.get(f"{API}/leaves/{lid}").json()["status"] == "Pending"
    assert len(client.get(f"{API}/roster/versions").json()) == 1
    assert cells(client, v1["id"]) == before_codes
    bal = {b["leave_type"]: b for b in client.get(f"{API}/leaves/balance/{emp}").json()}
    assert bal["Casual"]["used"] == 0 and bal["Casual"]["pending"] == 1
    actions = {a["action"] for a in client.get(f"{API}/roster/audit-log").json()}
    assert "leave_approved" not in actions and "leave_roster_impact" not in actions
    # only Pending leave can be previewed
    client.post(f"{API}/leaves/{lid}/approve", json={"auto_roster": False})
    assert client.post(f"{API}/leaves/{lid}/preview").status_code == 409


# --------------------------------------------------------- approve impact --

def test_approve_returns_removed_replacements_and_stored_impact(client):
    v1 = gen(client)
    client.post(f"{API}/roster/versions/{v1['id']}/publish")
    d = date(2026, 11, 4)
    emp = working_emp(client, v1["id"], d)
    lid = apply(client, emp, "Sick", str(d), str(d))
    body = client.post(f"{API}/leaves/{lid}/approve", json={"decided_by": "hr"}).json()
    imp = body["impact"]
    v2 = body["roster_version"]
    assert imp["base_version_id"] == v1["id"] and imp["new_version_id"] == v2["id"]
    assert len(imp["removed_assignments"]) == 1 and imp["removed_assignments"][0]["date"] == str(d)
    assert imp["shortage_total_after"] == 0 and imp["shortages"] == []
    new = cells(client, v2["id"])
    for rep in imp["replacements"]:  # every proposed replacement really is in the new draft
        assert new[rep["employee_id"]][(date.fromisoformat(rep["date"]) - START).days] == rep["to"]
    assert imp["off_day_plan"] is None  # one day is not a long leave
    stored = client.get(f"{API}/leaves/{lid}/impact").json()["impact"]
    assert stored["new_version_id"] == v2["id"] and stored["removed_assignments"] == imp["removed_assignments"]
    # leave cell in the draft is protected: cancel the leave instead of editing the roster
    edit = {"employee_id": emp, "work_date": str(d), "code": "M", "reason": "test change"}
    assert client.put(f"{API}/roster/versions/{v2['id']}/assignments", json=edit).status_code == 409
    other = {"employee_id": "T001", "work_date": "2026-11-05", "code": "SL", "reason": "test change"}
    assert client.put(f"{API}/roster/versions/{v2['id']}/assignments", json=other).status_code == 422


# ------------------------------------------------------------ replacements --

def test_replacement_candidates_for_a_short_shift(client):
    v = gen(client)
    d = date(2026, 11, 2)
    emp = next(e for e, c in cells(client, v["id"]).items() if c[(d - START).days] == "M")
    assert client.put(f"{API}/roster/versions/{v['id']}/assignments",
                      json={"employee_id": emp, "work_date": str(d), "code": "R", "reason": "test change"}).status_code == 200
    r = client.get(f"{API}/roster/versions/{v['id']}/replacements", params={"work_date": str(d), "shift": "M", "limit": 50})
    assert r.status_code == 200, r.text
    cands = r.json()["candidates"]
    assert emp in [c["employee_id"] for c in cands]  # the reserve we just created is a valid cover
    assert cands[0]["option"] == "reserve"           # reserve people rank first
    assert all(c["option"] in ("reserve", "weekly_off_call_in") or c["option"].startswith("move_from_") for c in cands)
    assert all(c["current_code"] not in ("SL", "CL", "AL", "-") for c in cands)
    assert client.get(f"{API}/roster/versions/{v['id']}/replacements",
                      params={"work_date": str(d), "shift": "X"}).status_code == 422
    assert client.get(f"{API}/roster/versions/{v['id']}/replacements",
                      params={"work_date": "2027-01-01", "shift": "M"}).status_code == 422


# --------------------------------------------------- long-leave off-day plan --

def test_long_leave_replans_weekly_off_and_half_duty(client):
    v1 = gen(client)
    emp = "T010"  # weekly off Wednesday, half-duty Saturday (see helpers.seed_small)
    lid = apply(client, emp, "Annual", "2026-10-26", "2026-11-01")  # 7 continuous days
    body = client.post(f"{API}/leaves/{lid}/approve", json={"decided_by": "hr"}).json()
    plan = body["off_day_plan"]
    assert plan["effective_from"] == "2026-11-02" and plan["continuous_days"] == 7  # next Monday
    assert plan["previous_weekly_off"] == "Wednesday" and plan["weekly_off"] != "Wednesday"
    assert plan["half_duty"] is not None and plan["half_duty"] != plan["weekly_off"]
    assert body["impact"]["off_day_plan"] == plan

    new = cells(client, body["roster_version"]["id"])[emp]
    assert [c for c in new[:7] if c != "WO"] == ["AL"] * 6  # leave week: Leave, except the old weekly-off day
    for k in range(7):  # Nov 2 .. Nov 8
        d = date(2026, 11, 2 + k)
        code = new[(d - START).days]
        if DAYS[d.weekday()] == plan["weekly_off"]:
            assert code == "WO", f"{d}: expected WO on the new weekly off, got {code}"
        else:
            assert code != "WO", f"{d}: old/other weekday must not be off any more ({code})"
    # the plan is persisted and later rosters honour it too
    assert len(plans(client)) == 1
    g = client.post(f"{API}/roster/generate", json={"start_date": "2026-11-02", "days": 7, **Q}).json()
    codes = cells(client, g["id"])[emp]
    wo_days = [DAYS[date(2026, 11, 2 + k).weekday()] for k, c in enumerate(codes) if c == "WO"]
    assert wo_days == [plan["weekly_off"]]
    # other people's weekly offs are untouched
    other = client.get(f"{API}/employees/T009").json()
    assert other["weekly_off_day"] == DAYS[8 % 7]


def test_five_day_leave_is_not_a_long_leave(client):
    gen(client)
    lid = apply(client, "T010", "Annual", "2026-10-27", "2026-10-31")  # exactly 5 days
    body = client.post(f"{API}/leaves/{lid}/approve").json()
    assert body["off_day_plan"] is None and plans(client) == []


def test_adjacent_leaves_chain_into_one_long_leave(client):
    gen(client)
    a = apply(client, "T010", "Sick", "2026-10-26", "2026-10-28")
    b = apply(client, "T010", "Annual", "2026-10-29", "2026-11-01")
    assert client.post(f"{API}/leaves/{a}/approve").json()["off_day_plan"] is None  # 3 days so far
    second = client.post(f"{API}/leaves/{b}/approve").json()
    assert second["off_day_plan"]["continuous_days"] == 7
    assert len(plans(client)) == 1


def test_cancelling_a_long_leave_removes_its_future_plan(client):
    gen(client)
    lid = apply(client, "T010", "Annual", "2026-10-26", "2026-11-01")
    client.post(f"{API}/leaves/{lid}/approve")
    assert len(plans(client)) == 1
    res = client.post(f"{API}/leaves/{lid}/cancel", json={"decided_by": "hr"}).json()
    assert res["off_day_plans_removed"] == 1 and plans(client) == []
    assert res["roster_version"] is not None  # roster re-optimised with the leave released
    latest = cells(client, res["roster_version"]["id"])["T010"]
    assert latest[0] != "AL"


def test_half_day_leave_does_not_replan_and_pending_changes_nothing(client):
    v1 = gen(client)
    lid = apply(client, "T011", "Casual", "2026-11-03", "2026-11-03", half_day=True)
    assert plans(client) == []
    assert len(client.get(f"{API}/roster/versions").json()) == 1  # pending leave never touches the roster
    body = client.post(f"{API}/leaves/{lid}/approve").json()
    assert body["off_day_plan"] is None and body["roster_version"]["trigger"] == "leave_approved"


def test_engine_effective_dated_plan_lookup():
    e = EmpIn(emp_id="X", weekly_off=2, half_duty=5,
              plans=((date(2026, 11, 2), 4, None), (date(2026, 11, 16), 1, 6)))
    assert e.weekly_off_on(date(2026, 11, 1)) == 2 and e.half_duty_on(date(2026, 11, 1)) == 5
    assert e.weekly_off_on(date(2026, 11, 2)) == 4 and e.half_duty_on(date(2026, 11, 9)) is None
    assert e.weekly_off_on(date(2026, 11, 20)) == 1 and e.half_duty_on(date(2026, 11, 20)) == 6
