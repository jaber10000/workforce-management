"""Step 8: night-shift rules on a generated roster, plus shortage handling when night cover is impossible."""
from datetime import timedelta

from app.models.employee import Employee
from sqlalchemy import select

from tests.helpers import DAYS, START, check_rules
from tests.test_leave_and_versions import Q, client, gen  # noqa: F401  (client is a fixture)


def _grid(client, vid):
    g = client.get(f"/api/v1/roster/versions/{vid}").json()["grid"]
    return g["days"], {r["employee_id"]: r["codes"] for r in g["rows"]}


def test_generated_roster_obeys_night_rules(client):
    v = gen(client)
    s = client.Session()
    emps = {e.employee_id: e for e in s.scalars(select(Employee))}
    days, codes = _grid(client, v["id"])
    dates = [START + timedelta(days=i) for i in range(len(days))]
    check_rules(codes, dates, emps)  # weekly off, night eligibility, no N->M, <=3 nights, <=6 working days
    nights = sum(1 for c in codes.values() for x in c if x.startswith("N"))
    assert nights > 0


def test_only_night_eligible_staff_get_night_and_no_morning_after_night(client):
    v = gen(client)
    s = client.Session()
    eligible = {e.employee_id for e in s.scalars(select(Employee)) if e.is_shift_eligible_night}
    _, codes = _grid(client, v["id"])
    for emp, row in codes.items():
        for i, c in enumerate(row):
            if c.startswith("N"):
                assert emp in eligible, f"{emp} is not night-eligible"
            if i and row[i - 1].startswith("N"):
                assert not row[i].startswith("M"), f"{emp}: night then morning on day {i}"


def test_no_more_than_three_consecutive_nights_even_under_heavy_night_demand(client):
    r = client.put("/api/v1/roster/requirements", json=[
        {"work_date": str(START + timedelta(days=k)), "morning_required": 8, "evening_required": 6,
         "night_required": 12, "min_senior": 1} for k in range(14)])
    assert r.status_code == 200
    v = gen(client)
    _, codes = _grid(client, v["id"])
    for emp, row in codes.items():
        run = 0
        for c in row:
            run = run + 1 if c.startswith("N") else 0
            assert run <= 3, f"{emp} has {run} nights in a row"


def test_impossible_night_demand_is_reported_as_shortage_and_needs_acknowledgement(client):
    client.put("/api/v1/roster/requirements", json=[
        {"work_date": str(START + timedelta(days=k)), "morning_required": 5, "evening_required": 4,
         "night_required": 60, "min_senior": 1} for k in range(14)])  # only ~35 night-eligible people exist
    v = gen(client)
    cov = client.get(f"/api/v1/roster/versions/{v['id']}/coverage").json()
    assert cov["has_shortage"] and cov["totals"]["night"] > 0
    assert all(d["shifts"]["night"]["assigned"] <= 60 for d in cov["days"])
    r = client.post(f"/api/v1/roster/versions/{v['id']}/publish")
    assert r.status_code == 409  # shortage must be acknowledged explicitly
    ok = client.post(f"/api/v1/roster/versions/{v['id']}/publish", json={"acknowledge_shortage": True})
    assert ok.status_code == 200 and ok.json()["status"] == "published"


def test_manual_edit_cannot_put_ineligible_employee_on_night(client):
    v = gen(client)
    s = client.Session()
    ineligible = next(e.employee_id for e in s.scalars(select(Employee)) if not e.is_shift_eligible_night)
    d = START + timedelta(days=3)
    _, codes = _grid(client, v["id"])
    if not codes[ineligible][3].startswith(("M", "E")):
        d = START + timedelta(days=next(i for i, c in enumerate(codes[ineligible]) if c[:1] in "ME"))
    r = client.put(f"/api/v1/roster/versions/{v['id']}/assignments",
                   json={"employee_id": ineligible, "work_date": str(d), "code": "N", "reason": "test"})
    assert r.status_code in (409, 422) and "not eligible" in r.json()["detail"].lower()
