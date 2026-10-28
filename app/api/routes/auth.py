import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, actor_name, get_db, get_principal, admin_required
from app.core.config import settings
from app.core.security import create_token, hash_password, verify_password
from app.models.employee import Employee, RolePool
from app.models.user import ROLES, AppUser
from app.services import audit

router = APIRouter(prefix="/auth", tags=["Auth"])

_failures: dict[str, deque] = defaultdict(deque)  # per-process brute-force guard (use a shared store behind many workers)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=200)
    role: str = "employee"
    employee_id: str | None = None
    full_name: str | None = Field(default=None, max_length=150)  # creates the employee profile if the ID has none yet
    team: str | None = Field(default=None, max_length=40)


class AccountRow(BaseModel):
    username: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str | None = Field(default=None, max_length=200)  # empty / "(unchanged)" keeps the current password of an existing account
    role: str = "employee"
    employee_id: str | None = None
    name: str | None = Field(default=None, max_length=150)
    team: str | None = Field(default=None, max_length=40)


class AccountsBulk(BaseModel):
    rows: list[AccountRow] = Field(min_length=1, max_length=1000)


class UserUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=200)
    role: str | None = None
    employee_id: str | None = None
    is_active: bool | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


def _user_out(u: AppUser) -> dict:
    return {"username": u.username, "role": u.role, "employee_id": u.employee_id, "is_active": u.is_active}


def _locked(username: str) -> bool:
    window = settings.login_lockout_minutes * 60
    q = _failures[username]
    while q and time.monotonic() - q[0] > window:
        q.popleft()
    return len(q) >= settings.login_max_failures


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    if _locked(body.username):
        raise HTTPException(429, f"Too many failed attempts. Try again in {settings.login_lockout_minutes} minutes")
    user = db.scalar(select(AppUser).where(AppUser.username == body.username))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        _failures[body.username].append(time.monotonic())
        audit.log(db, "login_failed", "user", body.username, {}, actor=body.username)
        db.commit()
        raise HTTPException(401, "Incorrect username or password")
    _failures.pop(body.username, None)
    audit.log(db, "login", "user", user.username, {}, actor=user.username)
    db.commit()
    return {"access_token": create_token(user.username, user.role), "token_type": "bearer", **_user_out(user)}


@router.get("/me")
def me(p: Principal = Depends(get_principal)):
    return {"username": p.username, "role": p.role, "employee_id": p.employee_id, "auth_required": settings.auth_required}


@router.post("/change-password", status_code=204)
def change_password(body: PasswordChange, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    user = db.scalar(select(AppUser).where(AppUser.username == p.username))
    if not user or not verify_password(body.current_password, user.password_hash):
        raise HTTPException(401, "Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    audit.log(db, "password_changed", "user", user.username, {}, actor=user.username)
    db.commit()


@router.get("/users")
def list_users(db: Session = Depends(get_db), _: Principal = Depends(admin_required)):
    return [_user_out(u) for u in db.scalars(select(AppUser).order_by(AppUser.username))]


@router.post("/users", status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), p: Principal = Depends(admin_required)):
    if body.role not in ROLES:
        raise HTTPException(422, f"role must be one of {ROLES}")
    eid = (body.employee_id or "").strip() or None
    if body.role == "employee" and not eid:
        raise HTTPException(422, "employee users must be linked to an employee_id")
    if db.scalar(select(AppUser.id).where(AppUser.username == body.username)):
        raise HTTPException(409, "Username already exists")
    created_profile = False
    if eid:
        emp = db.scalar(select(Employee).where(func.lower(Employee.employee_id) == eid.lower()))
        if emp:
            eid = emp.employee_id  # keep the stored spelling (t001 -> T001)
            if body.team and not emp.team:
                emp.team = body.team
        elif body.full_name and body.full_name.strip():
            # No profile yet: create it together with the account instead of failing with "Employee not found".
            emp = Employee(employee_id=eid, full_name=body.full_name.strip(), team=body.team,
                           role_pool=RolePool.supervisor if body.role == "supervisor" else RolePool.general)
            db.add(emp)
            audit.log(db, "employee_created", "employee", eid, {"name": emp.full_name, "via": "user_account"}, actor=p.username)
            created_profile = True
        else:
            raise HTTPException(422, f"Employee ID '{eid}' has no profile yet. Enter the person's full name to create "
                                     "the profile together with the account, or leave Employee ID empty "
                                     "(allowed for supervisor / manager / admin).")
    user = AppUser(username=body.username, password_hash=hash_password(body.password), role=body.role, employee_id=eid)
    db.add(user)
    audit.log(db, "user_created", "user", body.username, {"role": body.role, "employee_id": eid,
                                                          "profile_created": created_profile}, actor=p.username)
    db.commit()
    return {**_user_out(user), "profile_created": created_profile}


@router.post("/users/bulk")
def bulk_accounts(body: AccountsBulk, db: Session = Depends(get_db), p: Principal = Depends(admin_required)):
    """Create or update many accounts from a credentials CSV (username, password, role, employee_id, name, team).
    Existing usernames get the listed password/role/link (the way to repair accounts that 'do not log in'); missing
    employee profiles are created from `name`; one bad row never blocks the others."""
    created = updated = profiles = 0
    errors: list[dict] = []
    seen: set[str] = set()
    for i, r in enumerate(body.rows, start=1):
        def bad(msg: str):
            errors.append({"row": i, "username": r.username, "error": msg})
        if r.role not in ROLES:
            bad(f"role must be one of {ROLES}")
            continue
        if r.username.lower() in seen:
            bad("listed twice")
            continue
        seen.add(r.username.lower())
        user = db.scalar(select(AppUser).where(AppUser.username == r.username))
        pw = (r.password or "").strip()
        keep_pw = user is not None and pw in ("", "(unchanged)")
        if not keep_pw and len(pw) < 8:
            bad("password must be at least 8 characters")
            continue
        if user and user.username == p.username and (r.role != user.role):
            bad("you cannot change your own role here")
            continue
        eid = (r.employee_id or "").strip() or None
        if r.role == "employee" and not eid:
            bad("employee accounts need an employee_id")
            continue
        if eid:
            emp = db.scalar(select(Employee).where(func.lower(Employee.employee_id) == eid.lower()))
            if emp:
                eid = emp.employee_id
                if r.team:
                    emp.team = r.team
            elif r.name and r.name.strip():
                db.add(Employee(employee_id=eid, full_name=r.name.strip(), team=r.team or None,
                                role_pool=RolePool.supervisor if r.role == "supervisor" else RolePool.general))
                profiles += 1
            else:
                bad(f"Employee ID '{eid}' has no profile: add the name column to create it")
                continue
        if user:
            user.role, user.employee_id, user.is_active = r.role, eid, True
            if not keep_pw:
                user.password_hash = hash_password(pw)
            _failures.pop(user.username, None)
            updated += 1
        else:
            db.add(AppUser(username=r.username, password_hash=hash_password(pw), role=r.role, employee_id=eid))
            created += 1
        db.flush()
    audit.log(db, "users_bulk", "user", "bulk", {"created": created, "updated": updated, "profiles_created": profiles,
                                                 "rejected": len(errors)}, actor=p.username)
    db.commit()
    return {"created": created, "updated": updated, "profiles_created": profiles, "rejected": len(errors), "errors": errors}


@router.patch("/users/{username}")
def update_user(username: str, body: UserUpdate, db: Session = Depends(get_db), p: Principal = Depends(admin_required)):
    user = db.scalar(select(AppUser).where(AppUser.username == username))
    if not user:
        raise HTTPException(404, "User not found")
    changes = body.model_dump(exclude_unset=True)
    if "role" in changes and changes["role"] not in ROLES:
        raise HTTPException(422, f"role must be one of {ROLES}")
    if username == p.username and (changes.get("is_active") is False or ("role" in changes and changes["role"] != "admin")):
        raise HTTPException(409, "You cannot disable or demote your own account")
    if "password" in changes:
        user.password_hash = hash_password(changes.pop("password"))
        audit.log(db, "password_reset", "user", username, {}, actor=p.username)
    for k, v in changes.items():
        setattr(user, k, v)
    if changes:
        audit.log(db, "user_updated", "user", username, changes, actor=p.username)
    _failures.pop(username, None)
    db.commit()
    return _user_out(user)
