from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_db, manager_required
from app.services import import_service
from app.services.roster_service import RosterError

router = APIRouter(prefix="/imports", tags=["Import"])


@router.post("/roster")
async def import_roster(
    request: Request,
    dry_run: bool = True,
    week_start: date | None = None,
    employees: bool = True,
    requirements: bool = True,
    roster: bool = True,
    filename: str | None = Query(default=None, max_length=120),
    db: Session = Depends(get_db),
    p: Principal = Depends(manager_required),
):
    """Import an Excel workbook (raw .xlsx bytes as the request body, no multipart needed).

    Defaults to a dry run: everything is executed and rolled back so the counts are exact. Send dry_run=false to save.
    Weekly_Roster columns named Monday..Sunday need `week_start`; columns holding dates need nothing.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > import_service.MAX_BYTES:
        raise HTTPException(413, "File is too large")
    data = await request.body()
    try:
        return import_service.import_workbook_bytes(
            db, data, actor=p.username, dry_run=dry_run, week_start=week_start, employees=employees,
            requirements=requirements, roster=roster, filename=filename)
    except RosterError as exc:
        raise HTTPException(exc.status_code, exc.message)
