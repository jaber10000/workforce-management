import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_db, manager_required, review_required
from app.services import audit, team_service

router = APIRouter(prefix="/teams", tags=["Teams"])


@router.get("")
def list_teams(db: Session = Depends(get_db), _: Principal = Depends(review_required)):
    """Teams with size, supervisor, senior agents and night-eligible count (employees do not see this)."""
    return team_service.team_summary(team_service.active_employees(db))


@router.post("/auto-assign")
def auto_assign(teams: int = Query(default=5, ge=1, le=20), seniors_per_team: int = Query(default=2, ge=0, le=10),
                dry_run: bool = True, seed: int | None = Query(default=None, ge=0, le=2**31 - 1),
                db: Session = Depends(get_db), p: Principal = Depends(manager_required)):
    """Split all active employees into balanced teams (1 supervisor + N seniors each). `dry_run=true` (default) only
    shows the plan; call again with `dry_run=false` to save it. Re-running recomputes every team from scratch."""
    emps = team_service.active_employees(db)
    if not emps:
        raise HTTPException(409, "There are no active employees to split into teams")
    seed = secrets.randbelow(2**31) if seed is None else seed  # random by default; pass the preview's seed to save that exact plan
    try:
        plan, warnings = team_service.plan_teams(emps, teams, seniors_per_team, seed)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    changed = sum(1 for e in emps if e.team != plan.get(e.employee_id))
    before = {e.employee_id: e.team for e in emps}
    if not dry_run:
        for e in emps:
            e.team = plan.get(e.employee_id)
        audit.log(db, "teams_assigned", "team", "all", {"teams": teams, "seniors_per_team": seniors_per_team, "seed": seed,
                                                       "employees": len(emps), "changed": changed}, actor=p.username)
        db.commit()
    else:
        for e in emps:  # summary of the *proposed* plan without touching the DB
            e.team = plan.get(e.employee_id)
        summary = team_service.team_summary(emps)
        db.rollback()
        return {"dry_run": True, "seed": seed, "changed": changed, "warnings": warnings, "teams": summary}
    return {"dry_run": False, "seed": seed, "changed": changed, "warnings": warnings,
            "teams": team_service.team_summary(emps), "previous_unassigned": sum(1 for v in before.values() if v is None)}


@router.post("/rename-to-leaders")
def rename_to_leaders(db: Session = Depends(get_db), p: Principal = Depends(manager_required)):
    """Rename "Team 1", "Team 2" ... to "Team <supervisor name>" without moving anyone."""
    renamed = team_service.rename_numbered_teams(db)
    if renamed:
        audit.log(db, "teams_renamed", "team", "all", {"renamed": renamed}, actor=p.username)
        db.commit()
    left = sorted({e.team for e in team_service.active_employees(db) if e.team and team_service.NUMBERED.match(e.team)})
    return {"renamed": renamed, "still_numbered": left, "teams": team_service.team_summary(team_service.active_employees(db))}
