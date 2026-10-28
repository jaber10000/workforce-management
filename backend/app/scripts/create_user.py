"""Create (or reset) a login account.

    python -m app.scripts.create_user admin --role admin
    python -m app.scripts.create_user manager1 --role manager
    python -m app.scripts.create_user EMP021 --role employee --employee-id EMP021

The password is read from the PASSWORD environment variable or prompted for (never passed on the command line)."""
import argparse
import getpass
import os

from sqlalchemy import select

from app import models  # noqa: F401
from app.core.security import hash_password
from app.db.session import Base, SessionLocal, engine
from app.models.employee import Employee, RolePool
from app.models.user import ROLES, AppUser


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("username")
    ap.add_argument("--role", choices=ROLES, default="employee")
    ap.add_argument("--employee-id")
    ap.add_argument("--full-name", help="creates the employee profile too when --employee-id has none yet")
    a = ap.parse_args()
    password = os.environ.get("PASSWORD") or getpass.getpass("Password (min 8 chars): ")
    if len(password) < 8:
        raise SystemExit("Password must be at least 8 characters")
    if a.role == "employee" and not a.employee_id:
        raise SystemExit("--employee-id is required for employee accounts")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if a.employee_id and not db.scalar(select(Employee.id).where(Employee.employee_id == a.employee_id)):
            if not a.full_name:
                raise SystemExit(f"Employee '{a.employee_id}' has no profile: add --full-name to create it, or omit --employee-id")
            db.add(Employee(employee_id=a.employee_id, full_name=a.full_name,
                            role_pool=RolePool.supervisor if a.role == "supervisor" else RolePool.general))
            print(f"Created employee profile {a.employee_id}")
        u = db.scalar(select(AppUser).where(AppUser.username == a.username))
        if u:
            u.password_hash, u.role, u.employee_id, u.is_active = hash_password(password), a.role, a.employee_id, True
            print(f"Updated {a.username} ({a.role})")
        else:
            db.add(AppUser(username=a.username, password_hash=hash_password(password), role=a.role,
                           employee_id=a.employee_id))
            print(f"Created {a.username} ({a.role})")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
