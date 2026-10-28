"""Engine tests on the 5 demo workbooks (real size: 200+ employees, 14 days)."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.employee import Employee
from app.scripts.import_employees import import_workbook
from app.scripts.import_roster_inputs import import_inputs
from app.services import roster_service as svc
from tests.helpers import START, check_rules

LIMIT = 12


def by_key(files, key):
    return next(f for f in files if key in f.name)


@pytest.fixture(scope="module")
def solved(demo_files):
    """Solve each demo scenario once per test module."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.db.session import Base
    cache = {}

    def run(key):
        if key in cache:
            return cache[key]
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        db = sessionmaker(bind=engine)()
        path = by_key(demo_files, key)
        import_workbook(path, db=db)
        import_inputs(path, db=db)
        v = svc.generate_roster(db, start_date=START, end_date=START + timedelta(days=13), time_limit=LIMIT)
        cache[key] = (db, v)
        return cache[key]
    return run


def _check(db, v):
    grid = svc.roster_grid(db, v.id)
    emps = {e.employee_id: e for e in db.scalars(select(Employee))}
    days = [START + timedelta(days=i) for i in range(14)]
    check_rules({r["employee_id"]: r["codes"] for r in grid["rows"]}, days, emps)
    return grid, emps


def test_standard_has_no_shortage_and_respects_rules(solved):
    db, v = solved("01_standard")
    _check(db, v)
    cov = svc.coverage_report(db, v.id)
    assert cov["totals"]["total"] == 0 and not cov["has_shortage"]
    fair = svc.fairness_report(db, v.id)
    assert fair["summary"]["night_spread"] <= 3
    assert all(r["max_consecutive_nights"] <= 3 for r in fair["employees"])


def test_night_shortage_is_reported(solved):
    db, v = solved("02_night_shortage")
    _check(db, v)
    cov = svc.coverage_report(db, v.id)
    assert cov["totals"]["night"] > 0 and cov["has_shortage"]
    assert cov["totals"]["morning"] == 0 and cov["totals"]["evening"] == 0
    assert any(d["status"] == "SHORTAGE" for d in cov["days"])
    assert v.summary["days_with_shortage"] > 0
    with pytest.raises(svc.RosterError, match="shortage"):
        svc.publish(db, v.id)


def test_senior_shortage_is_reported(solved):
    db, v = solved("03_senior_tight")
    _check(db, v)
    cov = svc.coverage_report(db, v.id)
    assert cov["totals"]["senior"] > 0
    assert cov["totals"]["night"] == 0


def test_leave_heavy_syncs_approved_leave_and_covers_demand(solved):
    db, v = solved("04_leave_heavy")
    grid, _ = _check(db, v)
    codes = {r["employee_id"]: r["codes"] for r in grid["rows"]}
    from app.models.leave import LeaveApplication
    leaves = [l for l in db.scalars(select(LeaveApplication)) if l.status == "Approved" and not l.half_day]
    assert leaves
    emps = {e.employee_id: e for e in db.scalars(select(Employee))}
    for lv in leaves:
        for i in range(14):
            d = START + timedelta(days=i)
            e = emps[lv.employee_id]
            if lv.start_date <= d <= lv.end_date and e.weekly_off_day.value != d.strftime("%A") and d >= e.joining_date:
                assert codes[lv.employee_id][i] in ("SL", "CL", "AL")
    cov = svc.coverage_report(db, v.id)
    assert cov["totals"]["total"] == 0
    assert any(c.endswith("-H") for row in codes.values() for c in row)  # half duty / half leave


def test_new_joiners_not_rostered_before_joining(solved):
    db, v = solved("05_new_joiners")
    grid, emps = _check(db, v)
    for r in grid["rows"]:
        e = emps[r["employee_id"]]
        for i, c in enumerate(r["codes"]):
            if START + timedelta(days=i) < e.joining_date:
                assert c == "-"
    assert svc.coverage_report(db, v.id)["totals"]["total"] == 0
