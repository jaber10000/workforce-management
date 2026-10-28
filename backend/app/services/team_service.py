"""Split the workforce into teams, one supervisor and a fixed number of senior agents per team.

Default: 5 teams, 2 senior agents per team (10 seniors), one supervisor per team (5 supervisors); everybody else is dealt
out so every team ends up the same size (+/- 1) with a similar mix of night-eligible people, genders and weekly-off days.
The plan is deterministic (sorted by employee id), so running it twice gives the same teams."""
import random
from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.employee import Employee, RolePool


def team_name(i: int) -> str:  # placeholder only; always replaced by the leader's name in plan_teams
    return f"Team {i + 1}"


def leader_team_name(leader: Employee) -> str:
    return f"Team {leader.full_name}"


def plan_teams(emps: list[Employee], teams: int = 5, seniors_per_team: int = 2,
               seed: int | None = None) -> tuple[dict[str, str], list[str]]:
    """Return ({employee_id: team name}, warnings). Only the given (active) employees are planned.
    Each team is named after its leader ("Team <supervisor name>"). Who leads which people is random (`seed` makes a
    plan reproducible: the preview and the saved plan use the same seed) but sizes and the shift-pool mix stay balanced."""
    rng = random.Random(seed)
    warnings: list[str] = []
    sizes = [0] * teams
    stratum_count: list[Counter] = [Counter() for _ in range(teams)]
    out: dict[str, str] = {}
    names: list[str] = [team_name(i) for i in range(teams)]

    def put(e: Employee, t: int, key=None):
        out[e.employee_id] = names[t]
        sizes[t] += 1
        if key is not None:
            stratum_count[t][key] += 1

    ordered = sorted(emps, key=lambda e: e.employee_id)
    sups = [e for e in ordered if e.role_pool == RolePool.supervisor]
    seniors = [e for e in ordered if e.role_pool == RolePool.senior_support]
    rest = [e for e in ordered if e.role_pool not in (RolePool.supervisor, RolePool.senior_support)]

    if not sups:
        raise ValueError("No supervisor (team leader) found. Teams are named after their leader, so add supervisors first.")
    if len(sups) < teams:  # never fall back to "Team 1" style names: one team per leader
        warnings.append(f"Only {len(sups)} supervisor(s) for {teams} requested teams: making {len(sups)} team(s).")
        teams = len(sups)
        sizes, stratum_count = [0] * teams, [Counter() for _ in range(teams)]
        names = [team_name(i) for i in range(teams)]
    rng.shuffle(sups)  # random leader <-> team pairing; the leader gives the team its name
    used: Counter = Counter()
    for i, e in enumerate(sups[:teams]):
        n = leader_team_name(e)
        used[n] += 1
        names[i] = n if used[n] == 1 else f"{n} ({e.employee_id})"
    if len(sups) > teams:
        warnings.append(f"{len(sups)} supervisor(s) found for {teams} teams: the extra supervisor(s) join a team as members.")
    if len(seniors) != teams * seniors_per_team:
        warnings.append(f"{len(seniors)} senior agent(s) found; {teams} teams x {seniors_per_team} = {teams * seniors_per_team} expected.")

    for i, e in enumerate(sups):
        put(e, i % teams)
    # seniors: night-eligible ones first so every team gets some, then dealt to the team with the fewest seniors
    rng.shuffle(seniors)
    seniors.sort(key=lambda e: not e.is_shift_eligible_night)  # stable: night-eligible first, random inside each group
    senior_n = [0] * teams
    for e in seniors:
        t = min(range(teams), key=lambda x: (senior_n[x], sizes[x], x))
        senior_n[t] += 1
        put(e, t)
    # everyone else: stratified deal (night-eligible, gender, weekly off) into the currently smallest team
    def key(e: Employee):
        return (bool(e.is_shift_eligible_night), e.gender.value if e.gender else "", e.weekly_off_day.value if e.weekly_off_day else "")
    rng.shuffle(rest)
    rest.sort(key=key)  # stable: strata in order, random inside each stratum
    for e in rest:
        k = key(e)
        t = min(range(teams), key=lambda x: (sizes[x], stratum_count[x][k], x))
        put(e, t, k)
    return out, warnings


def team_summary(emps: list[Employee]) -> list[dict]:
    by: dict[str, list[Employee]] = defaultdict(list)
    for e in emps:
        by[e.team or "Unassigned"].append(e)

    def sort_key(name: str):
        return (name == "Unassigned", name)

    rows = []
    for name in sorted(by, key=sort_key):
        m = by[name]
        rows.append({
            "team": name, "size": len(m),
            "supervisors": [{"employee_id": e.employee_id, "full_name": e.full_name} for e in m if e.role_pool == RolePool.supervisor],
            "seniors": [{"employee_id": e.employee_id, "full_name": e.full_name} for e in m if e.role_pool == RolePool.senior_support],
            "night_eligible": sum(1 for e in m if e.is_shift_eligible_night),
            "male": sum(1 for e in m if e.gender and e.gender.value == "male"),
            "female": sum(1 for e in m if e.gender and e.gender.value == "female"),
        })
    return rows


def active_employees(db: Session) -> list[Employee]:
    return list(db.scalars(select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.employee_id)))


import re as _re

NUMBERED = _re.compile(r"^Team \d+$")


def rename_numbered_teams(db: Session) -> dict[str, str]:
    """Teams still called "Team 1", "Team 2" ... are renamed after the supervisor in them ("Team Arif").
    Members stay where they are. A team without a supervisor keeps its name (reported by the caller)."""
    emps = list(db.scalars(select(Employee)))
    by: dict[str, list[Employee]] = defaultdict(list)
    for e in emps:
        if e.team and NUMBERED.match(e.team):
            by[e.team].append(e)
    taken = {e.team for e in emps if e.team and not NUMBERED.match(e.team)}
    renamed: dict[str, str] = {}
    for old in sorted(by):
        leaders = sorted((e for e in by[old] if e.role_pool == RolePool.supervisor), key=lambda e: e.employee_id)
        if not leaders:
            continue
        new = leader_team_name(leaders[0])
        if new in taken:
            new = f"{new} ({leaders[0].employee_id})"
        taken.add(new)
        for e in by[old]:
            e.team = new
        renamed[old] = new
    return renamed
