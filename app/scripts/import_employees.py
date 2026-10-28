"""Import/upsert Employee_Master rows from an Excel workbook.

Usage from backend directory:
    python -m app.scripts.import_employees path/to/workbook.xlsx
"""
import argparse
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import func, select

from app.models.employee import Employee, Gender, RolePool, Weekday
from app import models  # noqa: F401


def clean(value):
    if value is None:
        return None
    result = str(value).strip()
    if len(result) > 1 and result[0] == "'" and result[1] in "=+-@":  # undo the export's formula-injection guard
        result = result[1:]
    return result or None


# Column names written by the Excel export (Step 7) -> names this importer understands, so a file exported
# from the app can be edited and imported back.
HEADER_ALIASES = {"Full Name": "Employee Name", "Phone": "Phone Number", "Role Pool": "Role / Pool",
                  "Weekly Off": "Weekly Off Day", "Half Duty Day": "Half-duty Day"}
SHEET_NAMES = ("Employee_Master", "Employees")


def parse_weekday(value):
    if not value:
        return None
    normalized = str(value).strip().capitalize()
    aliases = {day.value.lower(): day for day in Weekday}
    return aliases.get(normalized.lower())


def map_gender(value):
    if not value:
        return None
    text = str(value).strip().lower()
    if text in {"female", "f", "woman", "মহিলা"}:
        return Gender.female
    if text in {"male", "m", "man", "পুরুষ"}:
        return Gender.male
    if text in {"other", "অন্যান্য"}:
        return Gender.other
    return None


def map_role(value):
    text = (str(value).strip().lower() if value else "")
    if "senior" in text:
        return RolePool.senior_support
    if "supervisor" in text or "supervis" in text:
        return RolePool.supervisor
    if "general" in text:
        return RolePool.general
    return RolePool.other if text else RolePool.general


def parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def parse_bool(value, default=None):
    """Yes/No, Y/N, true/false, 1/0 -> bool. Empty -> default."""
    if value is None or str(value).strip() == "":
        return default
    text = str(value).strip().lower()
    if text in {"yes", "y", "true", "1", "active"}:
        return True
    if text in {"no", "n", "false", "0", "inactive"}:
        return False
    return default


def import_workbook(path, db=None, commit: bool = True):
    """Upsert employees from the Employee_Master sheet.

    Optional columns (used when present): Joining Date, Morning Eligible, Evening Eligible,
    Night Eligible, Active, Notes, Team. Pass `db` (a SQLAlchemy Session) to use a specific database,
    e.g. SQLite in tests; otherwise the configured application database is used.
    `path` may be a file path or a file-like object. With commit=False the caller owns the transaction
    (used by the in-app import's dry run); changes are only flushed.
    """
    own_session = db is None
    if own_session:
        from app.db.session import Base, SessionLocal, engine

        Base.metadata.create_all(bind=engine)
        db = SessionLocal()

    wb = load_workbook(path, read_only=True, data_only=True)
    sheet = next((n for n in SHEET_NAMES if n in wb.sheetnames), None)
    if sheet is None:
        wb.close()
        if own_session:
            db.close()
        raise ValueError("Workbook must contain an 'Employee_Master' sheet")
    ws = wb[sheet]
    rows = ws.iter_rows(values_only=True)
    headers = [clean(v) for v in next(rows)]
    header_map = {HEADER_ALIASES.get(h, h): i for i, h in enumerate(headers) if h}

    required = ["Employee ID", "Employee Name"]
    missing = [h for h in required if h not in header_map]
    if missing:
        wb.close()
        if own_session:
            db.close()
        raise ValueError(f"Missing required column(s): {', '.join(missing)}")

    created = updated = skipped = 0
    errors = []
    seen: set[str] = set()
    try:
        for row_number, row in enumerate(rows, start=2):
            try:
                emp_id = clean(row[header_map["Employee ID"]])
                name = clean(row[header_map["Employee Name"]])
                if not emp_id or not name:
                    skipped += 1
                    continue

                if emp_id.lower() in seen:
                    errors.append(f"Row {row_number}: duplicate Employee ID '{emp_id}' in the file - row ignored")
                    continue
                seen.add(emp_id.lower())

                def val(header):
                    idx = header_map.get(header)
                    return clean(row[idx]) if idx is not None and idx < len(row) else None

                def raw(header):
                    idx = header_map.get(header)
                    return row[idx] if idx is not None and idx < len(row) else None

                values = {
                    "full_name": name,
                    "gender": map_gender(val("Gender")),
                    "phone_number": val("Phone Number (Demo)") or val("Phone Number"),
                    "home_thana": val("Home Thana"),
                    "role_pool": map_role(val("Role / Pool")),
                    "weekly_off_day": parse_weekday(val("Weekly Off Day")),
                    "half_duty_day": parse_weekday(val("Half-duty Day")),
                    "notes": val("Notes"),
                }
                # Optional columns: only touch the DB field when the column exists.
                if "Team" in header_map:  # absent column must not wipe teams assigned in the app
                    values["team"] = val("Team")
                if "Joining Date" in header_map:
                    values["joining_date"] = parse_date(raw("Joining Date"))
                if "Morning Eligible" in header_map:
                    values["is_shift_eligible_morning"] = parse_bool(raw("Morning Eligible"), True)
                if "Evening Eligible" in header_map:
                    values["is_shift_eligible_evening"] = parse_bool(raw("Evening Eligible"), True)
                if "Night Eligible" in header_map:
                    values["is_shift_eligible_night"] = parse_bool(raw("Night Eligible"), False)
                values["is_active"] = (
                    parse_bool(raw("Active"), True) if "Active" in header_map else True
                )

                existing = db.scalar(select(Employee).where(func.lower(Employee.employee_id) == emp_id.lower()))
                if existing:
                    for key, value in values.items():
                        setattr(existing, key, value)
                    updated += 1
                else:
                    db.add(Employee(employee_id=emp_id, **values))
                    db.flush()  # later rows see it; keeps duplicate-ID detection honest inside one transaction
                    created += 1
            except Exception as exc:
                errors.append(f"Row {row_number}: {exc}")
        if commit:
            db.commit()
        else:
            db.flush()
    except Exception:
        if commit:
            db.rollback()
        raise
    finally:
        wb.close()
        if own_session:
            db.close()
    return created, updated, skipped, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook", type=Path, help="Path to roster Excel workbook")
    args = parser.parse_args()
    if not args.workbook.exists():
        raise SystemExit(f"File not found: {args.workbook}")
    created, updated, skipped, errors = import_workbook(args.workbook)
    print(f"Created: {created}; updated: {updated}; skipped: {skipped}; errors: {len(errors)}")
    for error in errors:
        print(error)


if __name__ == "__main__":
    main()
