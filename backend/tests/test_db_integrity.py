"""Step 9: migrations, unique IDs, invalid/duplicate requests, transactions & rollback, error messages, prod config."""
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.config import DEFAULT_SECRET, Settings
from app.models.employee import Employee
from app.models.leave import LeaveApplication
from app.services import leave_service
from app.services.leave_service import LeaveError
from tests.test_leave_and_versions import client  # noqa: F401  (fixture)
from tests.test_production import API, hdr, sec  # noqa: F401  (fixtures)

BACKEND = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 30)


# ------------------------------------------------------------- migrations --

def run_alembic(url, *args):
    env = {**os.environ, "DATABASE_URL": url}
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True)


def test_migrations_upgrade_fresh_db_and_are_repeatable(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    r = run_alembic(url, "upgrade", "head")
    assert r.returncode == 0, r.stderr
    eng = create_engine(url)
    tables = set(inspect(eng).get_table_names())
    assert {"employees", "leave_applications", "roster_versions", "roster_assignments", "audit_logs", "app_users",
            "swap_requests", "off_day_plans", "alembic_version"} <= tables
    assert run_alembic(url, "upgrade", "head").returncode == 0  # re-running is harmless
    assert "0006" in run_alembic(url, "current").stderr + run_alembic(url, "current").stdout
    down = run_alembic(url, "downgrade", "0001")
    assert down.returncode == 0, down.stderr
    assert run_alembic(url, "upgrade", "head").returncode == 0


def test_migration_adds_step5_columns_to_a_step4_database(tmp_path):
    """An old database (roster_versions without the approval columns) is upgraded in place, data kept."""
    url = f"sqlite:///{tmp_path / 'old.db'}"
    eng = create_engine(url)
    from app.db.session import Base
    Base.metadata.create_all(eng)
    with eng.begin() as c:
        for col in ("created_by", "approved_by", "approved_at", "review_note", "published_by", "published_at"):
            c.execute(text(f"ALTER TABLE roster_versions DROP COLUMN {col}"))
        c.execute(text("INSERT INTO employees (employee_id, full_name, role_pool, is_shift_eligible_morning,"
                       " is_shift_eligible_evening, is_shift_eligible_night, is_active)"
                       " VALUES ('OLD1', 'Old Timer', 'general', 1, 1, 0, 1)"))
    assert run_alembic(url, "upgrade", "head").returncode == 0
    cols = {c["name"] for c in inspect(eng).get_columns("roster_versions")}
    assert {"created_by", "approved_by", "approved_at", "review_note", "published_by", "published_at"} <= cols
    with eng.connect() as c:
        assert c.execute(text("SELECT full_name FROM employees WHERE employee_id='OLD1'")).scalar() == "Old Timer"


def test_db_level_uniqueness_after_migration(tmp_path):
    url = f"sqlite:///{tmp_path / 'u.db'}"
    assert run_alembic(url, "upgrade", "head").returncode == 0
    eng = create_engine(url)
    ins = ("INSERT INTO employees (employee_id, full_name, role_pool, is_shift_eligible_morning, is_shift_eligible_evening,"
           " is_shift_eligible_night, is_active) VALUES (:i, 'x', 'general', 1, 1, 0, 1)")
    with eng.begin() as c:
        c.execute(text(ins), {"i": "E1"})
    with pytest.raises(IntegrityError):
        with eng.begin() as c:
            c.execute(text(ins), {"i": "e1"})  # same ID, different case: rejected by the database itself
    leave = ("INSERT INTO leave_applications (application_id, employee_id, leave_type, start_date, end_date, half_day, days, status)"
             " VALUES (:a, 'E1', 'Casual', '2026-11-05', '2026-11-05', 0, 1, :s)")
    with eng.begin() as c:
        c.execute(text(leave), {"a": "LV1", "s": "Pending"})
        c.execute(text(leave), {"a": "LV2", "s": "Rejected"})  # a rejected one does not block a re-application
    with pytest.raises(IntegrityError):
        with eng.begin() as c:
            c.execute(text(leave), {"a": "LV3", "s": "Pending"})  # live duplicate for the same employee + date


def test_alembic_models_have_no_unmigrated_drift(tmp_path):
    """Every model table/column exists after `alembic upgrade head` (guards 'forgot to add a migration')."""
    url = f"sqlite:///{tmp_path / 'd.db'}"
    assert run_alembic(url, "upgrade", "head").returncode == 0
    insp = inspect(create_engine(url))
    from app.db.session import Base
    for table in Base.metadata.sorted_tables:
        have = {c["name"] for c in insp.get_columns(table.name)}
        assert {c.name for c in table.columns} <= have, f"{table.name} is missing columns after migration"


# ------------------------------------------------------ invalid & duplicate --

def apply(sec, h, **kw):
    body = {"employee_id": "T001", "leave_type": "Casual", "start_date": "2026-11-05", "end_date": "2026-11-05", **kw}
    return sec.post(f"{API}/leaves", json=body, headers=h)


@pytest.mark.parametrize("kw,fragment", [
    ({"start_date": "2026-11-06", "end_date": "2026-11-05"}, "End date cannot be before start date"),
    ({"start_date": "1999-01-01", "end_date": "1999-01-02"}, "not a valid leave date"),
    ({"start_date": "2026-09-01", "end_date": "2026-09-01"}, "older than 30 days"),
    ({"start_date": "2028-06-01", "end_date": "2028-06-01"}, "days ahead"),
    ({"start_date": "2026-11-01", "end_date": "2027-02-28", "leave_type": "Annual"}, "at most 90 days"),
    ({"half_day": True, "start_date": "2026-11-05", "end_date": "2026-11-06"}, "single day"),
    ({"leave_type": "Annual", "half_day": True}, "half day"),
])
def test_invalid_leave_dates_are_rejected_with_a_clear_reason(sec, kw, fragment):
    emp = hdr(sec, "emp1")
    r = apply(sec, emp, **kw)
    assert r.status_code == 422 and fragment in r.json()["detail"], r.text


def test_malformed_dates_and_unknown_values_return_field_errors(sec):
    emp = hdr(sec, "emp1")
    r = apply(sec, emp, start_date="2026-02-30")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "start_date"
    r = apply(sec, emp, leave_type="Holiday")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "leave_type"
    assert sec.get(f"{API}/leaves?from_date=not-a-date", headers=emp).status_code == 422
    assert apply(sec, emp, employee_id="NOBODY").status_code == 403  # employees cannot even name another ID


def test_manager_may_backdate_but_not_absurdly(sec):
    mgr = hdr(sec, "mgr1")
    assert apply(sec, mgr, leave_type="Sick", start_date="2026-09-20", end_date="2026-09-20").status_code == 201
    assert apply(sec, mgr, start_date="1990-01-01", end_date="1990-01-01").status_code == 422
    assert apply(sec, mgr, employee_id="NOBODY").status_code == 404


def test_duplicate_leave_request_is_rejected_and_reapply_after_reject_works(sec):
    emp, mgr = hdr(sec, "emp1"), hdr(sec, "mgr1")
    first = apply(sec, emp)
    assert first.status_code == 201
    dup = apply(sec, emp)  # double click / retry
    assert dup.status_code == 409 and "Overlaps existing leave" in dup.json()["detail"] and first.json()["application_id"] in dup.json()["detail"]
    overlap = apply(sec, emp, start_date="2026-11-04", end_date="2026-11-06")
    assert overlap.status_code == 409
    assert sec.get(f"{API}/leaves", headers=emp).json()["total"] == 1  # nothing half-saved
    sec.post(f"{API}/leaves/{first.json()['application_id']}/reject", json={"note": "busy"}, headers=mgr)
    assert apply(sec, emp).status_code == 201  # rejected leave frees the dates


def test_double_approve_is_rejected_and_balance_not_double_counted(sec):
    emp, mgr = hdr(sec, "emp1"), hdr(sec, "mgr1")
    lid = apply(sec, emp, start_date="2026-11-05", end_date="2026-11-07").json()["application_id"]
    assert sec.post(f"{API}/leaves/{lid}/approve", json={"auto_roster": False}, headers=mgr).status_code == 200
    again = sec.post(f"{API}/leaves/{lid}/approve", json={"auto_roster": False}, headers=mgr)
    assert again.status_code == 409 and "Only Pending" in again.json()["detail"]
    bal = {b["leave_type"]: b for b in sec.get(f"{API}/leaves/balance/T001?year=2026", headers=emp).json()}
    assert bal["Casual"]["used"] == 3 and bal["Casual"]["remaining"] == 7


def test_insufficient_balance_message(sec):
    emp = hdr(sec, "emp1")
    r = apply(sec, emp, start_date="2026-11-01", end_date="2026-11-11")  # 11 casual days, entitlement 10
    assert r.status_code == 409 and "Insufficient Casual leave balance" in r.json()["detail"]


# ------------------------------------------------------- transaction/rollback --

def test_failed_leave_application_leaves_no_partial_rows(sqlite_session):
    db = sqlite_session
    db.add(Employee(employee_id="R1", full_name="Rollback"))
    db.commit()
    with pytest.raises(LeaveError):
        leave_service.apply_leave(db, employee_id="R1", leave_type="Casual", start_date=date(2026, 11, 1),
                                  end_date=date(2026, 11, 20), today=TODAY)  # 20 days > balance
    db.rollback()
    assert db.scalar(select(LeaveApplication.id)) is None
    from app.models.roster import AuditLog
    assert db.scalar(select(AuditLog.id)) is None  # the audit row of the failed attempt was not kept either


def test_get_db_rolls_back_uncommitted_work_when_request_fails(tmp_path, monkeypatch):
    import app.db.session as session_mod
    eng = create_engine(f"sqlite:///{tmp_path / 'tx.db'}")
    from app.db.session import Base
    Base.metadata.create_all(eng)
    monkeypatch.setattr(session_mod, "SessionLocal", sessionmaker(bind=eng, autoflush=False))
    gen = session_mod.get_db()
    db = next(gen)
    db.add(Employee(employee_id="HALF", full_name="Never committed"))
    db.flush()
    with pytest.raises(RuntimeError):
        gen.throw(RuntimeError("handler blew up"))
    with eng.connect() as c:
        assert c.execute(text("SELECT count(*) FROM employees")).scalar() == 0


def test_integrity_errors_become_409_not_500(sec):
    """Even a race that slips past the application checks must surface as a friendly 409."""
    from fastapi.testclient import TestClient
    from sqlalchemy.exc import IntegrityError as IE
    from app.main import app

    @app.get("/__dup_employee")
    def dup_employee():
        raise IE("INSERT", {}, Exception("UNIQUE constraint failed: employees.employee_id"))

    r = TestClient(app, raise_server_exceptions=False).get("/__dup_employee")
    assert r.status_code == 409 and r.json()["detail"] == "An employee with this ID already exists"
    from app.core.errors import _friendly_integrity
    assert "username" in _friendly_integrity(IE("x", {}, Exception("UNIQUE constraint failed: app_users.username"))).lower()
    assert "duplicate" in _friendly_integrity(IE("x", {}, Exception("duplicate key value violates uq_swap_open"))).lower()


def test_unhandled_error_hides_internals_and_carries_request_id(sec):
    from app.main import app
    from fastapi.testclient import TestClient

    @app.get("/__boom")
    def boom():
        raise RuntimeError("secret internal detail /etc/passwd")

    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/__boom", headers={"X-Request-ID": "abc123"})
    assert r.status_code == 500 and "secret" not in r.text and r.json()["request_id"] == "abc123"
    assert r.headers["x-request-id"] == "abc123" and r.headers["x-content-type-options"] == "nosniff"


def test_unauthenticated_and_forbidden_errors_have_readable_messages(sec):
    assert sec.get(f"{API}/employees").json()["detail"] == "Not authenticated"
    emp = hdr(sec, "emp1")
    assert sec.post(f"{API}/roster/generate", json={"start_date": "2026-10-26"}, headers=emp).json()["detail"] == \
        "You do not have permission for this action"
    r = sec.post(f"{API}/auth/login", json={"username": "emp1", "password": "wrong"})
    assert r.status_code == 401 and r.json()["detail"] == "Incorrect username or password"
    assert sec.get(f"{API}/roster/versions/99999", headers=hdr(sec, "mgr1")).json()["detail"] == "Roster version not found"


# ---------------------------------------------------------------- configuration --

def make_settings(**kw):
    base = dict(environment="prod", auth_required=True, secret_key="x" * 40,
                database_url="postgresql+psycopg://u:realpw@db:5432/w", cors_origins="https://roster.example.com",
                enable_docs=False, require_approval=True)
    return Settings(_env_file=None, **{**base, **kw})


def test_production_config_checks():
    assert make_settings().production_problems() == []
    assert any("SECRET_KEY" in p for p in make_settings(secret_key=DEFAULT_SECRET).production_problems())
    assert any("SECRET_KEY" in p for p in make_settings(secret_key="short").production_problems())
    assert any("AUTH_REQUIRED" in p for p in make_settings(auth_required=False).production_problems())
    assert any("CORS" in p for p in make_settings(cors_origins="*").production_problems())
    assert any("https" in p for p in make_settings(cors_origins="http://roster.example.com").production_problems())
    assert any("SQLite" in p for p in make_settings(database_url="sqlite:///x.db").production_problems())
    assert any("placeholder" in p for p in make_settings(database_url="postgresql://u:CHANGE_ME@h/d").production_problems())
    assert any("DOCS" in p for p in make_settings(enable_docs=True).production_problems())
    assert any("REQUIRE_APPROVAL" in p for p in make_settings(require_approval=False).production_problems())


def test_app_refuses_to_start_in_prod_with_bad_config(monkeypatch):
    from fastapi.testclient import TestClient
    from app.core.config import settings
    from app.main import app
    monkeypatch.setattr(settings, "environment", "prod")
    monkeypatch.setattr(settings, "secret_key", DEFAULT_SECRET)
    with pytest.raises(RuntimeError, match="Refusing to start in production"):
        with TestClient(app):
            pass


def test_security_headers_cors_and_health(sec):
    r = sec.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.headers["x-frame-options"] == "DENY"
    assert sec.get("/ready").json() == {"status": "ready"}
    ok = sec.options(f"{API}/auth/login", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = sec.options(f"{API}/auth/login", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="set TEST_DATABASE_URL to a scratch PostgreSQL to run")
def test_postgres_migration_and_constraints():
    """Real PostgreSQL check (CI service container): migrate, then the partial unique indexes must hold."""
    url = os.environ["TEST_DATABASE_URL"]
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE")); c.execute(text("CREATE SCHEMA public"))
    r = run_alembic(url, "upgrade", "head")
    assert r.returncode == 0, r.stderr
    with eng.begin() as c:
        c.execute(text("INSERT INTO employees (employee_id, full_name, role_pool, is_shift_eligible_morning,"
                       " is_shift_eligible_evening, is_shift_eligible_night, is_active)"
                       " VALUES ('P1','x','general',true,true,false,true)"))
    with pytest.raises(IntegrityError):
        with eng.begin() as c:
            c.execute(text("INSERT INTO employees (employee_id, full_name, role_pool, is_shift_eligible_morning,"
                           " is_shift_eligible_evening, is_shift_eligible_night, is_active)"
                           " VALUES ('p1','y','general',true,true,false,true)"))
    with pytest.raises(IntegrityError):
        with eng.begin() as c:
            c.execute(text("INSERT INTO leave_applications (application_id, employee_id, leave_type, start_date, end_date,"
                           " half_day, days, status) VALUES ('X','P1','Casual','2026-11-09','2026-11-01',false,1,'Pending')"))
