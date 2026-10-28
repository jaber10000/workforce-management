"""Excel reports (Step 7): weekly roster, employee list, leave report, shift coverage report.

Every workbook starts with an `Info` sheet that records what the file is, the roster version it came from
(number, status, period), who exported it and when. Data sheets get a styled header, frozen panes, filters,
sensible widths, real date cells, print setup and (where a column has a fixed vocabulary) drop-down validation.
`EXPECTED_COLUMNS` is the contract for each sheet; `check_columns` verifies a workbook against it.
"""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.employee import Employee, Gender, RolePool, Weekday
from app.models.leave import LeaveApplication
from app.models.roster import RosterVersion
from app.services import roster_service as svc

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ROSTER_CODES = ["M", "E", "N", "M-H", "E-H", "N-H", "R", "WO", "SL", "CL", "AL", "-"]
LEAVE_STATUSES = ["Pending", "Approved", "Rejected", "Cancelled"]

EXPECTED_COLUMNS: dict[str, list[str]] = {
    "employees": ["Employee ID", "Full Name", "Gender", "Phone", "Home Thana", "Role Pool", "Weekly Off",
                  "Half Duty Day", "Joining Date", "Morning Eligible", "Evening Eligible", "Night Eligible",
                  "Active", "Notes", "Team"],
    "leaves": ["Application ID", "Employee ID", "Employee Name", "Leave Type", "From", "To", "Days", "Half Day",
               "Status", "Reason", "Decided By", "Decided At (UTC)", "Decision Note", "Applied At (UTC)"],
    "coverage": ["Date", "Weekday", "Morning Required", "Morning Assigned", "Morning Short", "Evening Required",
                 "Evening Assigned", "Evening Short", "Night Required", "Night Assigned", "Night Short",
                 "Senior Short", "Status"],
}
WEEKLY_FIXED = ["Employee ID", "Employee Name", "Role"]

_HEAD_FILL = PatternFill("solid", fgColor="1F3A5F")
_HEAD_FONT = Font(bold=True, color="FFFFFF")
_THIN = Side(style="thin", color="BFBFBF")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_CODE_FILL = {"M": "FFF2CC", "E": "FCE4D6", "N": "D9D2E9", "WO": "D9D9D9", "R": "E2EFDA",
              "SL": "F8CBAD", "CL": "F8CBAD", "AL": "F8CBAD"}
_RED = PatternFill("solid", bgColor="F4B6B6", fgColor="F4B6B6")
_STATUS_FILL = {"Approved": "E2EFDA", "Pending": "FFF2CC", "Rejected": "F8CBAD", "Cancelled": "D9D9D9"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def safe(value):
    """Neutralise spreadsheet formula injection in user-entered text (=, +, @, or '-' followed by text)."""
    if isinstance(value, str) and value and (value[0] in "=+@" or (value[0] == "-" and len(value) > 1)
                                             or value[0] in "\t\r"):
        return "'" + value
    return value


def _xl_dt(dt: datetime | None):
    return dt.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0) if dt else None


# ---------------------------------------------------------------- helpers --

def new_workbook(title: str, meta: list[tuple[str, object]], *, exported_by: str, now: datetime | None = None) -> Workbook:
    now = now or utcnow()
    wb = Workbook()
    wb.properties.title, wb.properties.creator = title, "Workforce Roster"
    wb.properties.created = now.replace(tzinfo=None)
    info = wb.active
    info.title = "Info"
    rows = [("Report", title), *meta, ("Exported on (date)", now.date()), ("Exported at (UTC)", f"{now:%Y-%m-%d %H:%M}"),
            ("Exported by", exported_by)]
    for k, v in rows:
        info.append([k, safe(v) if isinstance(v, str) else v])
    for r in info.iter_rows(min_row=1, max_row=info.max_row):
        r[0].font = Font(bold=True)
        r[0].fill = PatternFill("solid", fgColor="E8EEF5")
        if isinstance(r[1].value, date) and not isinstance(r[1].value, datetime):
            r[1].number_format = "yyyy-mm-dd"
            r[1].alignment = Alignment(horizontal="left")
    info.column_dimensions["A"].width = 26
    info.column_dimensions["B"].width = 60
    wb.properties.subject = "; ".join(f"{k}={v}" for k, v in meta if k in ("Roster version", "Version status"))
    return wb


def write_table(ws, headers: list[str], rows: list[list], *, date_cols: tuple[int, ...] = (),
                datetime_cols: tuple[int, ...] = (), text_cols: tuple[int, ...] = (), center_cols: tuple[int, ...] = (),
                min_width: int = 10, max_width: int = 45, header_row: int = 1) -> None:
    """Write a header + rows (1-based column indexes in the *_cols arguments) and style the sheet."""
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=c, value=h)
        cell.fill, cell.font, cell.border = _HEAD_FILL, _HEAD_FONT, _BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[header_row].height = 30
    widths = [len(str(h)) + 2 for h in headers]
    for r_i, row in enumerate(rows, header_row + 1):
        for c_i, val in enumerate(row, 1):
            if isinstance(val, str):
                val = safe(val)
            cell = ws.cell(row=r_i, column=c_i, value=val)
            cell.border = _BORDER
            if c_i in date_cols and val is not None:
                cell.number_format = "yyyy-mm-dd"
                cell.alignment = Alignment(horizontal="center")
            elif c_i in datetime_cols and val is not None:
                cell.number_format = "yyyy-mm-dd hh:mm"
            elif c_i in text_cols:
                cell.number_format = "@"  # keeps leading zeros (phone numbers)
            if c_i in center_cols:
                cell.alignment = Alignment(horizontal="center")
            widths[c_i - 1] = max(widths[c_i - 1], min(len(str(val)) + 2 if val is not None else 0, max_width))
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = max(min_width, min(w, max_width))
    last = max(ws.max_row, header_row + 1)
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(headers))}{last}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{header_row}:{header_row}"
    ws.oddFooter.left.text = "&A"
    ws.oddFooter.right.text = "Page &P of &N"


def add_list_validation(ws, col: int, values: list[str], first_row: int, last_row: int, title: str) -> None:
    if last_row < first_row:
        return
    dv = DataValidation(type="list", formula1='"' + ",".join(values) + '"', allow_blank=True, showErrorMessage=True,
                        errorTitle=title, error=f"Allowed values: {', '.join(values)}")
    ws.add_data_validation(dv)
    letter = get_column_letter(col)
    dv.add(f"{letter}{first_row}:{letter}{last_row}")


def to_bytes(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def check_columns(ws, expected: list[str], header_row: int = 1) -> list[str]:
    """Return a list of problems (empty = the sheet has exactly the expected header)."""
    got = [c.value for c in ws[header_row]][: len(expected) + 3]
    got = [g for g in got if g is not None]
    problems = []
    for h in expected:
        if h not in got:
            problems.append(f"missing column '{h}'")
    for h in got:
        if h not in expected:
            problems.append(f"unexpected column '{h}'")
    if not problems and got != expected:
        problems.append("columns are in a different order")
    return problems


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in text).strip("-")


def filename(kind: str, *, key: str = "", version: RosterVersion | None = None, now: datetime | None = None) -> str:
    now = now or utcnow()
    parts = [kind]
    if key:
        parts.append(_slug(key))
    if version is not None:
        parts += [f"v{version.version_no}", version.status]
    parts.append(f"exported-{now:%Y-%m-%d}")
    return "_".join(parts) + ".xlsx"


def version_meta(v: RosterVersion) -> list[tuple[str, object]]:
    official = v.status == "published"
    return [
        ("Roster version", f"v{v.version_no} (id {v.id})"),
        ("Version status", "OFFICIAL - published" if official else f"NOT OFFICIAL - {v.status.upper()}"),
        ("Roster period", f"{v.start_date} to {v.end_date}"),
        ("Roster key", v.roster_key),
        ("Created by", v.created_by or ""),
        ("Approved by", f"{v.approved_by} on {v.approved_at:%Y-%m-%d %H:%M} UTC" if v.approved_by and v.approved_at else ""),
        ("Published by", f"{v.published_by} on {v.published_at:%Y-%m-%d %H:%M} UTC" if v.published_by and v.published_at else ""),
    ]


# ---------------------------------------------------------------- reports --

def pick_version(db: Session, *, version_id: int | None, week_start: date | None, manager: bool) -> RosterVersion:
    """Explicit id -> that version. Otherwise the published version covering the date (managers may fall back to
    the newest draft). Employees can only ever get a published version."""
    if version_id is not None:
        v = svc.get_version(db, version_id)
    else:
        stmt = select(RosterVersion).where(RosterVersion.status == "published")
        if week_start:
            stmt = stmt.where(RosterVersion.start_date <= week_start + timedelta(days=6),
                              RosterVersion.end_date >= week_start)
        v = db.scalar(stmt.order_by(RosterVersion.id.desc()).limit(1))
        if v is None and manager:
            v = svc.latest_version(db, week_start or date.min, (week_start or date.max) + timedelta(days=6)) \
                if week_start else db.scalar(select(RosterVersion).order_by(RosterVersion.id.desc()).limit(1))
        if v is None:
            raise svc.RosterError("No roster is available for this period", 404)
    if not manager and v.status != "published":
        raise svc.RosterError("Only published rosters can be exported by employees", 403)
    return v


def weekly_roster(db: Session, v: RosterVersion, week_start: date, *, exported_by: str, now: datetime | None = None) -> bytes:
    week_end = week_start + timedelta(days=6)
    if week_end < v.start_date or week_start > v.end_date:
        raise svc.RosterError(f"Version v{v.version_no} covers {v.start_date} to {v.end_date}, not this week", 422)
    grid = svc.roster_grid(db, v.id)
    idx = [i for i, d in enumerate(grid["days"]) if week_start <= date.fromisoformat(d["date"]) <= week_end]
    days = [grid["days"][i] for i in idx]
    wb = new_workbook("Weekly roster", [*version_meta(v), ("Week", f"{week_start} to {week_end}")],
                      exported_by=exported_by, now=now)
    ws = wb.create_sheet("Weekly Roster")
    headers = WEEKLY_FIXED + [f"{d['weekday'][:3]} {date.fromisoformat(d['date']):%d-%b}" for d in days]
    rows = [[r["employee_id"], r["employee_name"], r["role"]] + [r["codes"][i] for i in idx] for r in grid["rows"]]
    write_table(ws, headers, rows, center_cols=tuple(range(4, 4 + len(days))), min_width=9)
    first, last = 2, 1 + len(rows)
    for row in ws.iter_rows(min_row=first, max_row=last, min_col=4, max_col=3 + len(days)):
        for cell in row:
            val = str(cell.value)
            key = val[0] if val[0] in "MEN" and (len(val) == 1 or val.endswith("-H")) else val
            if key in _CODE_FILL:
                cell.fill = PatternFill("solid", fgColor=_CODE_FILL[key])
    if days:
        cl, cr = get_column_letter(4), get_column_letter(3 + len(days))
        dv = DataValidation(type="list", formula1='"' + ",".join(ROSTER_CODES) + '"', allow_blank=False,
                            showErrorMessage=True, errorTitle="Roster code", error="Use one of: " + ", ".join(ROSTER_CODES))
        ws.add_data_validation(dv)
        dv.add(f"{cl}{first}:{cr}{last}")
    # on-duty totals under the grid (weights: half duty = 0.5)
    ws.cell(row=last + 2, column=1, value="On duty (person-shifts)").font = Font(bold=True)
    for k, (label, letter) in enumerate((("Morning", "M"), ("Evening", "E"), ("Night", "N"))):
        r = last + 3 + k
        ws.cell(row=r, column=1, value=label).font = Font(bold=True)
        for j, i in enumerate(idx):
            total = sum((0.5 if r_["codes"][i].endswith("-H") else 1.0) for r_ in grid["rows"]
                        if r_["codes"][i][:1] == letter and r_["codes"][i] in (letter, f"{letter}-H"))
            c = ws.cell(row=r, column=4 + j, value=total)
            c.alignment = Alignment(horizontal="center")
    return to_bytes(wb)


def employee_list(db: Session, *, exported_by: str, is_active: bool | None = True, role_pool: RolePool | None = None,
                  now: datetime | None = None) -> bytes:
    stmt = select(Employee).order_by(Employee.employee_id)
    if is_active is not None:
        stmt = stmt.where(Employee.is_active == is_active)
    if role_pool is not None:
        stmt = stmt.where(Employee.role_pool == role_pool)
    emps = db.scalars(stmt).all()
    meta = [("Filter: active", "all" if is_active is None else ("yes" if is_active else "no")),
            ("Filter: role pool", role_pool.value if role_pool else "all"), ("Employees", len(emps))]
    wb = new_workbook("Employee list", meta, exported_by=exported_by, now=now)
    ws = wb.create_sheet("Employees")
    yn = lambda b: "Yes" if b else "No"  # noqa: E731
    rows = [[e.employee_id, e.full_name, e.gender.value if e.gender else None, e.phone_number, e.home_thana,
             e.role_pool.value, e.weekly_off_day.value if e.weekly_off_day else None,
             e.half_duty_day.value if e.half_duty_day else None, e.joining_date, yn(e.is_shift_eligible_morning),
             yn(e.is_shift_eligible_evening), yn(e.is_shift_eligible_night), yn(e.is_active), e.notes, e.team] for e in emps]
    write_table(ws, EXPECTED_COLUMNS["employees"], rows, date_cols=(9,), text_cols=(1, 4), center_cols=(10, 11, 12, 13))
    last = max(2, 1 + len(rows))
    add_list_validation(ws, 3, [g.value for g in Gender], 2, last, "Gender")
    add_list_validation(ws, 6, [r.value for r in RolePool], 2, last, "Role pool")
    add_list_validation(ws, 7, [w.value for w in Weekday], 2, last, "Weekday")
    add_list_validation(ws, 8, [w.value for w in Weekday], 2, last, "Weekday")
    for col in (10, 11, 12, 13):
        add_list_validation(ws, col, ["Yes", "No"], 2, last, "Yes / No")
    return to_bytes(wb)


def leave_report(db: Session, *, exported_by: str, from_date: date | None = None, to_date: date | None = None,
                 status: str | None = None, employee_id: str | None = None, leave_type: str | None = None,
                 now: datetime | None = None) -> bytes:
    stmt = select(LeaveApplication).order_by(LeaveApplication.start_date, LeaveApplication.id)
    if from_date:
        stmt = stmt.where(LeaveApplication.end_date >= from_date)
    if to_date:
        stmt = stmt.where(LeaveApplication.start_date <= to_date)
    if status:
        stmt = stmt.where(LeaveApplication.status == status)
    if employee_id:
        stmt = stmt.where(LeaveApplication.employee_id == employee_id)
    if leave_type:
        stmt = stmt.where(LeaveApplication.leave_type == leave_type)
    items = db.scalars(stmt).all()
    names = {e.employee_id: e.full_name for e in db.scalars(select(Employee).where(
        Employee.employee_id.in_({i.employee_id for i in items}))) } if items else {}
    meta = [("Period", f"{from_date or 'start'} to {to_date or 'end'}"), ("Filter: status", status or "all"),
            ("Filter: employee", employee_id or "all"), ("Filter: leave type", leave_type or "all"),
            ("Applications", len(items))]
    wb = new_workbook("Leave report", meta, exported_by=exported_by, now=now)
    ws = wb.create_sheet("Leave Applications")
    rows = [[i.application_id, i.employee_id, names.get(i.employee_id, ""), i.leave_type, i.start_date, i.end_date,
             i.days, "Yes" if i.half_day else "No", i.status, i.reason, i.decided_by, _xl_dt(i.decided_at),
             i.decision_note, _xl_dt(i.created_at)] for i in items]
    write_table(ws, EXPECTED_COLUMNS["leaves"], rows, date_cols=(5, 6), datetime_cols=(12, 14), center_cols=(7, 8, 9))
    for r in range(2, 2 + len(rows)):
        fill = _STATUS_FILL.get(ws.cell(row=r, column=9).value)
        if fill:
            ws.cell(row=r, column=9).fill = PatternFill("solid", fgColor=fill)
        ws.cell(row=r, column=7).number_format = "0.0"
    add_list_validation(ws, 9, LEAVE_STATUSES, 2, max(2, 1 + len(rows)), "Status")
    summ = wb.create_sheet("Summary")
    agg: dict[tuple[str, str], dict[str, float]] = {}
    for i in items:
        a = agg.setdefault((i.employee_id, i.leave_type), {"Approved": 0.0, "Pending": 0.0, "n": 0})
        a["n"] += 1
        if i.status in ("Approved", "Pending"):
            a[i.status] += i.days
    srows = [[e, names.get(e, ""), t, a["n"], a["Approved"], a["Pending"]] for (e, t), a in sorted(agg.items())]
    write_table(summ, ["Employee ID", "Employee Name", "Leave Type", "Applications", "Approved Days", "Pending Days"],
                srows, center_cols=(4, 5, 6))
    if srows:
        summ.append([])
        summ.append(["TOTAL", None, None, f"=SUM(D2:D{1 + len(srows)})", f"=SUM(E2:E{1 + len(srows)})",
                     f"=SUM(F2:F{1 + len(srows)})"])
        for c in summ[summ.max_row]:
            c.font = Font(bold=True)
    return to_bytes(wb)


def coverage_report(db: Session, v: RosterVersion, *, exported_by: str, now: datetime | None = None) -> bytes:
    cov = svc.coverage_report(db, v.id)
    t = cov["totals"]
    meta = [*version_meta(v), ("Days with shortage", cov["days_with_shortage"]),
            ("Total shortage (person-shifts)", t["total"]), ("Senior shortage", t["senior"])]
    wb = new_workbook("Shift coverage report", meta, exported_by=exported_by, now=now)
    ws = wb.create_sheet("Shift Coverage")
    rows = []
    for d in cov["days"]:
        m, e, n = (d["shifts"][k] for k in ("morning", "evening", "night"))
        rows.append([date.fromisoformat(d["date"]), d["weekday"], m["required"], m["assigned"], m["shortage"],
                     e["required"], e["assigned"], e["shortage"], n["required"], n["assigned"], n["shortage"],
                     d["senior_shortage_total"], d["status"]])
    write_table(ws, EXPECTED_COLUMNS["coverage"], rows, date_cols=(1,), center_cols=tuple(range(2, 14)))
    last = max(2, 1 + len(rows))
    for col in ("E", "H", "K", "L"):
        ws.conditional_formatting.add(f"{col}2:{col}{last}", CellIsRule(operator="greaterThan", formula=["0"], fill=_RED))
    ws.conditional_formatting.add(f"M2:M{last}", CellIsRule(operator="equal", formula=['"SHORTAGE"'], fill=_RED))
    if rows:
        ws.append([])
        ws.append(["TOTAL", None] + [None, None, f"=SUM(E2:E{last})", None, None, f"=SUM(H2:H{last})", None, None,
                                    f"=SUM(K2:K{last})", f"=SUM(L2:L{last})", None])
        for c in ws[ws.max_row]:
            c.font = Font(bold=True)
    return to_bytes(wb)
