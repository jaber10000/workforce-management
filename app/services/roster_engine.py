"""OR-Tools CP-SAT roster engine (pure Python, no database access).

Cell codes
    M / E / N        full duty          M-H / E-H / N-H  half duty (half-duty weekday or half-day leave)
    R                reserve / standby  WO               weekly off
    SL / CL / AL     approved full-day leave              -   not employed (inactive / before joining)

Hard rules
    * one code per employee per day; weekly off, approved leave and "not employed" are fixed
    * shift eligibility (M / E / N flags)
    * Night is never followed by a Morning shift; max 3 consecutive nights
    * max 6 consecutive working days; employees without a fixed weekly off get a flexible WO
    * a shift is never staffed above its requirement (+0.5 when a half-duty person is needed)
    * days before ``free_from`` are frozen (used to protect published history)

Soft rules (weighted objective, highest priority first)
    1. headcount shortage per shift, and Senior shortage per shift
    2. changes versus the base roster (minimal re-optimisation)
    3. fairness: spread of Night shifts, Evening shifts and total working days
    4. avoid Evening -> Morning quick turnarounds

Coverage is counted in half-units internally: full duty = 2, half duty = 1.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

from ortools.sat.python import cp_model

SHIFTS = ("M", "E", "N")
LEAVE_CODE = {"Sick": "SL", "Casual": "CL", "Annual": "AL"}
WORK_STREAK_MAX = 6
NIGHT_STREAK_MAX = 3

W_SHORTAGE = 100_000      # per half-unit of missing headcount
W_SENIOR_SHORTAGE = 60_000  # per half-unit of missing Senior cover
W_CHANGE = 400            # per changed cell versus the base roster
W_NIGHT_SPREAD = 300
W_EVENING_SPREAD = 100
W_WORK_SPREAD = 80
W_EVE_TO_MORNING = 15
POOL_MIN_FRACTION = 0.6   # employees available < 60% of the window are left out of the spread


class EngineError(RuntimeError):
    pass


@dataclass(frozen=True)
class EmpIn:
    emp_id: str
    senior: bool = False
    morning: bool = True
    evening: bool = True
    night: bool = False
    weekly_off: int | None = None   # Monday = 0
    half_duty: int | None = None
    joining: date | None = None
    active: bool = True
    # effective-dated (effective_from, weekly_off, half_duty), sorted; latest <= day wins
    plans: tuple = ()

    def weekly_off_on(self, d: date) -> int | None:
        off = self.weekly_off
        for eff, wo, _ in self.plans:
            if eff <= d:
                off = wo
        return off

    def half_duty_on(self, d: date) -> int | None:
        half = self.half_duty
        for eff, _, hd in self.plans:
            if eff <= d:
                half = hd
        return half


@dataclass(frozen=True)
class LeaveIn:
    emp_id: str
    start: date
    end: date
    kind: str
    half_day: bool = False


@dataclass(frozen=True)
class ReqIn:
    morning: int
    evening: int
    night: int
    min_senior: int


@dataclass
class EngineInput:
    start: date
    end: date
    employees: list[EmpIn]
    leaves: list[LeaveIn]
    requirements: dict[date, ReqIn]
    free_from: date | None = None                 # days before this are frozen
    frozen: dict[tuple[str, date], str] = field(default_factory=dict)
    history: dict[tuple[str, date], str] = field(default_factory=dict)  # days before ``start``
    base: dict[tuple[str, date], str] = field(default_factory=dict)     # for change minimisation
    time_limit: float = 30.0
    workers: int = 8
    seed: int = 7


@dataclass
class EngineResult:
    codes: dict[tuple[str, date], str]
    status: str
    objective: float | None
    best_bound: float | None
    seconds: float


# ---------------------------------------------------------------- helpers --

def code_shift(code: str) -> str | None:
    """'M-H' -> 'M'; non-duty codes -> None."""
    return code[0] if code and code[0] in SHIFTS and (len(code) == 1 or code[1:] == "-H") else None


def code_weight(code: str) -> float:
    shift = code_shift(code)
    if shift is None:
        return 0.0
    return 0.5 if code.endswith("-H") else 1.0


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _fixed_code(e: EmpIn, d: date, full_leave: dict[tuple[str, date], str]) -> str | None:
    if not e.active or (e.joining and d < e.joining):
        return "-"
    wo = e.weekly_off_on(d)
    if wo is not None and d.weekday() == wo:
        return "WO"
    return full_leave.get((e.emp_id, d))


# ------------------------------------------------------------------ solve --

def solve(inp: EngineInput) -> EngineResult:
    if inp.end < inp.start:
        raise EngineError("end date is before start date")
    days = list(_daterange(inp.start, inp.end))
    free_from = max(inp.free_from or inp.start, inp.start)
    free_days = [d for d in days if d >= free_from]
    hist_days = sorted({d for (_, d) in inp.history if d < inp.start})[-WORK_STREAK_MAX:]
    all_days = hist_days + days
    didx = {d: i for i, d in enumerate(all_days)}

    # leave lookup -------------------------------------------------------
    full_leave: dict[tuple[str, date], str] = {}
    half_leave: set[tuple[str, date]] = set()
    for lv in inp.leaves:
        for d in _daterange(max(lv.start, inp.start), min(lv.end, inp.end)):
            if lv.half_day:
                half_leave.add((lv.emp_id, d))
            else:
                full_leave[(lv.emp_id, d)] = LEAVE_CODE.get(lv.kind, "AL")

    model = cp_model.CpModel()
    # cells[(emp, day)] -> str (constant code) | dict(option -> BoolVar)
    cells: dict[tuple[str, date], object] = {}
    weight: dict[tuple[str, date], int] = {}
    n_var_cells = 0

    for e in inp.employees:
        for d in hist_days:
            cells[(e.emp_id, d)] = inp.history.get((e.emp_id, d), "-")
        for d in days:
            key = (e.emp_id, d)
            if d < free_from:
                cells[key] = inp.frozen.get(key) or _fixed_code(e, d, full_leave) or "R"
                continue
            fixed = _fixed_code(e, d, full_leave)
            if fixed is not None:
                cells[key] = fixed
                continue
            opts: dict[str, cp_model.IntVar] = {}
            if e.morning:
                opts["M"] = model.NewBoolVar(f"x_{e.emp_id}_{d}_M")
            if e.evening:
                opts["E"] = model.NewBoolVar(f"x_{e.emp_id}_{d}_E")
            if e.night:
                opts["N"] = model.NewBoolVar(f"x_{e.emp_id}_{d}_N")
            opts["R"] = model.NewBoolVar(f"x_{e.emp_id}_{d}_R")
            if e.weekly_off_on(d) is None:
                opts["WO"] = model.NewBoolVar(f"x_{e.emp_id}_{d}_WO")
            model.AddExactlyOne(opts.values())
            cells[key] = opts
            n_var_cells += 1
            hd = e.half_duty_on(d)
            half = (hd is not None and d.weekday() == hd) or key in half_leave
            weight[key] = 1 if half else 2

    def shift_expr(emp: str, d: date, s: str):
        c = cells[(emp, d)]
        if isinstance(c, str):
            return 1 if code_shift(c) == s else 0
        return c.get(s, 0)

    def work_expr(emp: str, d: date):
        c = cells[(emp, d)]
        if isinstance(c, str):
            return 1 if code_shift(c) else 0
        return sum_exprs([v for k, v in c.items() if k in SHIFTS])

    def is_const(emp: str, d: date) -> bool:
        return isinstance(cells[(emp, d)], str)

    def sum_exprs(items):
        return cp_model.LinearExpr.Sum(items) if items else 0

    # rest rules ---------------------------------------------------------
    pen_terms: list[tuple[int, object]] = []  # (weight, expr)
    for e in inp.employees:
        emp = e.emp_id
        # Night -> Morning forbidden, Evening -> Morning discouraged
        for a, b in zip(all_days, all_days[1:]):
            if is_const(emp, a) and is_const(emp, b):
                continue
            n, m = shift_expr(emp, a, "N"), shift_expr(emp, b, "M")
            if not (isinstance(n, int) and isinstance(m, int)):
                model.Add(n + m <= 1)
            ev = shift_expr(emp, a, "E")
            if not isinstance(ev, int) and not isinstance(m, int):
                p = model.NewBoolVar(f"em_{emp}_{b}")
                model.Add(p >= ev + m - 1)
                pen_terms.append((W_EVE_TO_MORNING, p))
        # max consecutive nights
        for i in range(len(all_days) - NIGHT_STREAK_MAX):
            win = all_days[i:i + NIGHT_STREAK_MAX + 1]
            if all(is_const(emp, d) for d in win):
                continue
            model.Add(sum_exprs([shift_expr(emp, d, "N") for d in win]) <= NIGHT_STREAK_MAX)
        # max consecutive working days
        for i in range(len(all_days) - WORK_STREAK_MAX):
            win = all_days[i:i + WORK_STREAK_MAX + 1]
            if all(is_const(emp, d) for d in win):
                continue
            model.Add(sum_exprs([work_expr(emp, d) for d in win]) <= WORK_STREAK_MAX)
        # flexible weekly off: at least one WO in every 7 day window (unless already off/leave)
        if e.weekly_off is None and not e.plans:
            for i in range(len(days) - 6):
                win = days[i:i + 7]
                if any(is_const(emp, d) and cells[(emp, d)] in ("WO", "SL", "CL", "AL", "-") for d in win):
                    continue
                wos = [cells[(emp, d)]["WO"] for d in win if not is_const(emp, d)]
                if wos:
                    model.Add(sum_exprs(wos) >= 1)

    # coverage -----------------------------------------------------------
    senior_ids = {e.emp_id for e in inp.employees if e.senior}
    short_vars: list[tuple[int, object]] = []
    for d in free_days:
        req = inp.requirements.get(d)
        if req is None:
            continue
        need = {"M": req.morning, "E": req.evening, "N": req.night}
        for s in SHIFTS:
            terms, sen_terms = [], []
            for e in inp.employees:
                c = cells[(e.emp_id, d)]
                if isinstance(c, str) or s not in c:
                    continue
                w = weight[(e.emp_id, d)]
                terms.append(w * c[s])
                if e.emp_id in senior_ids:
                    sen_terms.append(w * c[s])
            units = sum_exprs(terms)
            need2 = 2 * need[s]
            sh = model.NewIntVar(0, need2, f"short_{d}_{s}")
            model.Add(units + sh >= need2)
            model.Add(units <= need2 + 1)
            short_vars.append((W_SHORTAGE, sh))
            min_sen2 = 2 * min(req.min_senior, need[s])
            if min_sen2 > 0:
                ssh = model.NewIntVar(0, min_sen2, f"ssh_{d}_{s}")
                model.Add(sum_exprs(sen_terms) + ssh >= min_sen2)
                short_vars.append((W_SENIOR_SHORTAGE, ssh))

    # fairness -----------------------------------------------------------
    def total_expr(emp: str, shift: str | None):
        items = []
        for d in days:
            items.append(work_expr(emp, d) if shift is None else shift_expr(emp, d, shift))
        return sum_exprs(items)

    fair_terms: list[tuple[int, object]] = []
    n_free = max(len(free_days), 1)
    assignable = {
        e.emp_id: sum(1 for d in free_days if not is_const(e.emp_id, d)) for e in inp.employees
    }

    def spread(shift: str | None, eligible, weight_: int, tag: str):
        members = [e for e in inp.employees if eligible(e) and assignable[e.emp_id] > 0]
        if len(members) < 2:
            return
        hi = model.NewIntVar(0, len(days), f"hi_{tag}")
        lo = model.NewIntVar(0, len(days), f"lo_{tag}")
        pooled = 0
        for e in members:
            t = total_expr(e.emp_id, shift)
            model.Add(hi >= t)
            if assignable[e.emp_id] >= POOL_MIN_FRACTION * n_free:
                model.Add(lo <= t)
                pooled += 1
        if pooled == 0:
            model.Add(lo == 0)
        fair_terms.append((weight_, hi - lo))

    spread("N", lambda e: e.night, W_NIGHT_SPREAD, "N")
    spread("E", lambda e: e.evening, W_EVENING_SPREAD, "E")
    spread(None, lambda e: True, W_WORK_SPREAD, "W")

    # change minimisation versus base roster ------------------------------
    change_terms: list[object] = []
    hints: list[tuple[object, int]] = []
    if inp.base:
        for e in inp.employees:
            for d in free_days:
                c = cells[(e.emp_id, d)]
                if isinstance(c, str):
                    continue
                b = inp.base.get((e.emp_id, d))
                if b is None:
                    continue
                key = code_shift(b) or ("R" if b == "R" else ("WO" if b == "WO" else None))
                for opt, var in c.items():
                    hints.append((var, 1 if opt == key else 0))
                if key in c:
                    change_terms.append(1 - c[key])
                else:
                    change_terms.append(1)  # base cell no longer possible (e.g. leave) -> counted, unavoidable
    for var, val in hints:
        model.AddHint(var, val)

    shortage_expr = cp_model.LinearExpr.Sum([w * v for w, v in short_vars]) if short_vars else 0
    other = [w * v for w, v in pen_terms] + [w * v for w, v in fair_terms]
    if change_terms:
        other.append(W_CHANGE * sum_exprs([t for t in change_terms if not isinstance(t, int)]))
    other_expr = cp_model.LinearExpr.Sum(other) if other else 0

    def new_solver(seconds: float) -> cp_model.CpSolver:
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(float(seconds), 0.5)
        workers = max(1, min(inp.workers, os.cpu_count() or 1)) if inp.workers else 1
        solver.parameters.num_search_workers = workers
        solver.parameters.random_seed = inp.seed
        return solver

    # Phase 1: coverage first. Phase 2: keep that shortage level, optimise changes + fairness.
    started = time.monotonic()
    model.Minimize(shortage_expr)
    solver = new_solver(inp.time_limit * 0.45)
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise EngineError(f"solver returned {solver.StatusName(status)}: rules conflict with frozen/fixed assignments")
    best_shortage = int(round(solver.ObjectiveValue()))

    def adopt(sol: cp_model.CpSolver):
        model.ClearHints()
        for c in cells.values():
            if isinstance(c, dict):
                for var in c.values():
                    model.AddHint(var, sol.Value(var))

    solver1 = solver
    adopt(solver)
    if other:
        model.Add(shortage_expr <= best_shortage)
        model.Minimize(other_expr)
        solver2 = new_solver(inp.time_limit - (time.monotonic() - started))
        solver2.parameters.relative_gap_limit = 0.01
        status2 = solver2.Solve(model)
        if status2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            solver, status = solver2, status2
    status_name = solver.StatusName(status)
    objective_value = float(best_shortage) + (solver.ObjectiveValue() if solver is not solver1 else 0.0)

    codes: dict[tuple[str, date], str] = {}
    for e in inp.employees:
        for d in days:
            c = cells[(e.emp_id, d)]
            if isinstance(c, str):
                codes[(e.emp_id, d)] = c
                continue
            chosen = next(opt for opt, var in c.items() if solver.Value(var))
            if chosen in SHIFTS and weight[(e.emp_id, d)] == 1:
                chosen += "-H"
            codes[(e.emp_id, d)] = chosen
    return EngineResult(
        codes=codes, status=status_name, objective=float(objective_value),
        best_bound=None, seconds=time.monotonic() - started,
    )
