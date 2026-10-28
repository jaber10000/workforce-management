"""Shared helpers: small synthetic workforce so solver tests run in a couple of seconds."""
from datetime import date, timedelta

from app.models.employee import Employee, RolePool, Weekday
from app.services.roster_service import upsert_requirements

START = date(2026, 10, 26)
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def seed_small(db, n=70, start=START, days=14, req=(14, 10, 4, 1)):
    for i in range(n):
        db.add(Employee(
            employee_id=f"T{i + 1:03d}", full_name=f"Test {i + 1}",
            role_pool=RolePool.senior_support if i % 6 == 0 else RolePool.general,
            weekly_off_day=Weekday(DAYS[i % 7]),
            half_duty_day=Weekday(DAYS[(i + 3) % 7]) if i % 9 == 0 and DAYS[(i + 3) % 7] != DAYS[i % 7] else None,
            joining_date=date(2024, 1, 1),
            is_shift_eligible_night=(i % 2 == 0)))
    upsert_requirements(db, [
        {"work_date": start + timedelta(days=k), "morning_required": req[0], "evening_required": req[1],
         "night_required": req[2], "min_senior": req[3]} for k in range(days)])
    db.commit()


def check_rules(codes_by_emp: dict, days: list, emps: dict):
    """Independent validation of hard rules on {emp_id: [code per day]}."""
    for emp_id, codes in codes_by_emp.items():
        e = emps[emp_id]
        nights = work = 0
        for i, (d, c) in enumerate(zip(days, codes)):
            if e.weekly_off_day and DAYS[d.weekday()] == e.weekly_off_day.value and c != "-":
                assert c == "WO", f"{emp_id} {d}: expected WO got {c}"
            if c.startswith("N"):
                assert e.is_shift_eligible_night, f"{emp_id} non-night-eligible on night"
            if i and codes[i - 1].startswith("N"):
                assert not c.startswith("M"), f"{emp_id} night->morning on {d}"
            nights = nights + 1 if c.startswith("N") else 0
            assert nights <= 3, f"{emp_id} >3 consecutive nights"
            work = work + 1 if c[:1] in "MEN" and c not in ("-",) and not c.startswith("WO") else 0
            assert work <= 6, f"{emp_id} >6 consecutive working days"
