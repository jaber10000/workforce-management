"""Create / repair login accounts from a credentials CSV and verify that every login really works.

    python -m app.scripts.sync_accounts credentials.csv            # create or update accounts (sets the listed passwords)
    python -m app.scripts.sync_accounts credentials.csv --check    # only check: does each username + password log in?

CSV columns: username, password, role, employee_id, name, team (the file written by seed_team_portal --credentials-out).
Use this when accounts "do not log in": it talks to the database the app is configured for (DATABASE_URL) and prints
which one, so you can see if you seeded a different database than the one the running server uses."""
import argparse
import csv

from sqlalchemy import func, select

from app import models  # noqa: F401
from app.core.security import hash_password, verify_password
from app.db.session import Base, SessionLocal, engine
from app.models.employee import Employee, RolePool
from app.models.user import ROLES, AppUser


def read_rows(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--check", action="store_true", help="do not change anything, only verify the logins")
    a = ap.parse_args()
    rows = read_rows(a.csv)
    print(f"Database: {engine.url.render_as_string(hide_password=True)}")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    ok = bad = created = updated = 0
    try:
        for r in rows:
            name, pw, role = r.get("username", ""), r.get("password", ""), r.get("role", "employee") or "employee"
            if not name or role not in ROLES:
                print(f"  skipped row (username={name!r}, role={role!r})")
                continue
            u = db.scalar(select(AppUser).where(AppUser.username == name))
            if a.check:
                if not u:
                    print(f"  {name}: NO SUCH ACCOUNT in this database"); bad += 1
                elif not u.is_active:
                    print(f"  {name}: account is disabled"); bad += 1
                elif not verify_password(pw, u.password_hash):
                    print(f"  {name}: password does not match"); bad += 1
                else:
                    ok += 1
                continue
            eid = r.get("employee_id") or None
            if eid:
                emp = db.scalar(select(Employee).where(func.lower(Employee.employee_id) == eid.lower()))
                if emp:
                    eid = emp.employee_id
                    if r.get("team"):
                        emp.team = r["team"]
                elif r.get("name"):
                    db.add(Employee(employee_id=eid, full_name=r["name"], team=r.get("team") or None,
                                    role_pool=RolePool.supervisor if role == "supervisor" else RolePool.general))
                else:
                    print(f"  {name}: employee {eid} has no profile and no name column - skipped"); bad += 1
                    continue
            if len(pw) < 8 and not (u and pw in ("", "(unchanged)")):
                print(f"  {name}: password shorter than 8 characters - skipped"); bad += 1
                continue
            if u:
                u.role, u.employee_id, u.is_active = role, eid, True
                if pw not in ("", "(unchanged)"):
                    u.password_hash = hash_password(pw)
                updated += 1
            else:
                db.add(AppUser(username=name, password_hash=hash_password(pw), role=role, employee_id=eid))
                created += 1
            db.flush()
        if not a.check:
            db.commit()
    finally:
        db.close()
    if a.check:
        print(f"{ok} of {ok + bad} logins verified" + ("" if not bad else f"; {bad} problem(s) listed above"))
    else:
        print(f"{created} accounts created, {updated} updated, {bad} skipped. Run again with --check to verify.")


if __name__ == "__main__":
    main()
