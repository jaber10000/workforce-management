"""Seed the team portal: 200 employees in 5 supervisor-named teams, with login accounts and demo KPI.

    python -m app.scripts.seed_team_portal                       # employees + accounts + 3 months of demo KPI
    python -m app.scripts.seed_team_portal --no-kpi              # no demo KPI
    python -m app.scripts.seed_team_portal --credentials-out creds.csv

Layout (200 people): 5 supervisors (EMP196-EMP200), 10 senior agents (EMP006-EMP015) and 185 agents.
EMP001..EMP195 are dealt round-robin into the teams, so EMP001 -> Team Arif, EMP002 -> Team Rahman, EMP003 -> Team Miraz,
EMP004 -> Team Nusrat, EMP005 -> Team Ziarul, EMP006 -> Team Arif ... Each team ends with 1 supervisor, 2 senior agents
and 37 agents (40 people). Teams are named after their supervisor ("Team Rahman"), not "Team 1".

Accounts: supervisors log in as arif / rahman / miraz / nusrat / ziarul (password = name + 12345); every employee logs in with
their employee id in lower case (emp002) and the password emp00212345. Change these after the first login.
The script is safe to run again: people and accounts are updated, KPI rows are not overwritten."""
import argparse
import csv
import random
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.core.security import hash_password
from app.db.session import Base, SessionLocal, engine
from app.models.employee import Employee, Gender, RolePool, Weekday
from app.models.kpi import EmployeeKpi
from app.models.user import AppUser

SUPERVISORS = ["Arif", "Rahman", "Miraz", "Nusrat", "Ziarul"]
TOTAL = 200
SENIOR_IDS = {f"EMP{n:03d}" for n in range(6, 16)}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MALE = ["Abdul", "Rahim", "Karim", "Hasan", "Hossain", "Jamal", "Kamal", "Nasir", "Rafiq", "Sabbir", "Tanvir", "Imran",
        "Faisal", "Mahmud", "Shakil", "Mehedi", "Rubel", "Sohel", "Masud", "Habib", "Nayeem", "Shahin", "Tareq", "Zahid"]
FEMALE = ["Fatema", "Ayesha", "Sabina", "Rokeya", "Shirin", "Taslima", "Nasrin", "Farhana", "Mim", "Sumaiya", "Rina",
          "Lima", "Joya", "Mitu", "Popy", "Shila", "Dolly", "Anika", "Tania", "Sharmin", "Mou", "Jui"]
LAST = ["Ahmed", "Khan", "Chowdhury", "Islam", "Uddin", "Sarker", "Hossain", "Mia", "Akter", "Begum", "Khatun", "Talukder",
        "Biswas", "Mondal", "Sheikh", "Howlader", "Bhuiyan", "Miah", "Sikder", "Karim"]
THANAS = ["Mirpur", "Uttara", "Mohammadpur", "Dhanmondi", "Gulshan", "Banani", "Badda", "Rampura", "Khilgaon", "Motijheel",
          "Jatrabari", "Demra", "Savar", "Tejgaon", "Pallabi", "Kafrul"]


def team_name(sup: str) -> str:
    return f"Team {sup}"


def employee_password(emp_id: str) -> str:
    return f"{emp_id.lower()}12345"


def supervisor_password(name: str) -> str:
    return f"{name.lower()}12345"


def months_back(today: date, n: int) -> list[str]:
    y, m, out = today.year, today.month, []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def seed(db: Session, today: date, kpi_months: int = 3, seed_value: int = 2026) -> dict:
    rng = random.Random(seed_value)
    agents_n = TOTAL - len(SUPERVISORS)
    used: set[str] = set()
    people: list[dict] = []
    for i in range(agents_n):
        emp_id = f"EMP{i + 1:03d}"
        female = rng.random() < 0.45
        while True:
            name = f"{rng.choice(FEMALE if female else MALE)} {rng.choice(LAST)}"
            if name not in used:
                used.add(name)
                break
        senior = emp_id in SENIOR_IDS
        people.append({"id": emp_id, "name": name, "gender": Gender.female if female else Gender.male,
                       "role": RolePool.senior_support if senior else RolePool.general, "team": team_name(SUPERVISORS[i % 5]),
                       "night": (i % 2 == 0) if not senior else (i % 4 in (0, 1)), "off": WEEKDAYS[i % 7], "login_role": "employee"})
    for j, sup in enumerate(SUPERVISORS):
        people.append({"id": f"EMP{agents_n + j + 1:03d}", "name": sup, "gender": None, "role": RolePool.supervisor,
                       "team": team_name(sup), "night": False, "off": WEEKDAYS[(j + 2) % 7], "login_role": "supervisor",
                       "username": sup.lower(), "password": supervisor_password(sup)})

    existing = {e.employee_id: e for e in db.scalars(select(Employee))}
    users = {u.username: u for u in db.scalars(select(AppUser))}
    creds, new_emp, new_users = [], 0, 0
    for k, pr in enumerate(people):
        e = existing.get(pr["id"])
        if not e:
            e = Employee(employee_id=pr["id"], full_name=pr["name"])
            db.add(e)
            new_emp += 1
        e.full_name, e.gender, e.role_pool, e.team, e.is_active = pr["name"], pr["gender"], pr["role"], pr["team"], True
        e.weekly_off_day = Weekday(pr["off"])
        e.is_shift_eligible_morning, e.is_shift_eligible_evening, e.is_shift_eligible_night = True, True, pr["night"]
        e.joining_date = e.joining_date or date(rng.randint(2021, 2025), rng.randint(1, 12), rng.randint(1, 28))
        e.phone_number = e.phone_number or f"01700-{100000 + k:06d}"
        e.home_thana = e.home_thana or rng.choice(THANAS)
        username = pr.get("username") or pr["id"].lower()
        password = pr.get("password") or employee_password(pr["id"])
        u = users.get(username)
        if not u:
            db.add(AppUser(username=username, password_hash=hash_password(password), role=pr["login_role"], employee_id=pr["id"]))
            new_users += 1
        else:
            u.role, u.employee_id, u.is_active = pr["login_role"], pr["id"], True
            # existing passwords are never reset by a re-run
        creds.append({"username": username, "password": password if not u else "(unchanged)", "role": pr["login_role"],
                      "employee_id": pr["id"], "name": pr["name"], "team": pr["team"]})
    db.flush()

    kpi_new = 0
    if kpi_months:
        sup_user = {team_name(s): s.lower() for s in SUPERVISORS}
        have = {(k.employee_id, k.period) for k in db.scalars(select(EmployeeKpi))}
        periods = months_back(today, kpi_months)
        for pr in people:
            if pr["role"] == RolePool.supervisor:
                continue
            base = rng.gauss(81, 7)
            for idx, per in enumerate(periods):
                if (pr["id"], per) in have:
                    continue
                if per == periods[-1] and per == f"{today.year:04d}-{today.month:02d}" and int(pr["id"][3:]) % 5 in (0, 1):
                    continue  # the current month is only partly uploaded
                def m(shift=0.0):
                    return round(min(100.0, max(40.0, rng.gauss(base + shift + idx * 0.6, 4))), 1)
                q, a, pr_, c = m(1), m(4), m(-2), m(0)
                sup = sup_user[pr["team"]]
                db.add(EmployeeKpi(employee_id=pr["id"], period=per, quality=q, attendance=min(100.0, a), productivity=pr_, csat=c,
                                   score=round((q + min(100.0, a) + pr_ + c) / 4, 1), uploaded_by=sup,
                                   uploaded_by_name=sup.capitalize()))
                kpi_new += 1
    db.commit()
    return {"employees": len(people), "new_employees": new_emp, "new_accounts": new_users, "kpi_rows_added": kpi_new,
            "credentials": creds}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-kpi", action="store_true", help="do not create demo KPI rows")
    ap.add_argument("--kpi-months", type=int, default=3)
    ap.add_argument("--credentials-out", help="write usernames and initial passwords to this CSV file")
    a = ap.parse_args()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        r = seed(db, date.today(), 0 if a.no_kpi else a.kpi_months)
    finally:
        db.close()
    print(f"{r['employees']} employees ({r['new_employees']} new), {r['new_accounts']} new accounts, {r['kpi_rows_added']} KPI rows added")
    if a.credentials_out:
        with open(a.credentials_out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["username", "password", "role", "employee_id", "name", "team"])
            w.writeheader()
            w.writerows(r["credentials"])
        print(f"Credentials written to {a.credentials_out}")


if __name__ == "__main__":
    main()
