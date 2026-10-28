from dataclasses import dataclass
from datetime import date

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_token
from app.db.session import get_db  # noqa: F401  (re-exported)
from app.models.user import AppUser

_bearer = HTTPBearer(auto_error=False)


def get_today() -> date:
    """Dependency so tests can pin "today" (published-roster protection depends on it)."""
    return date.today()


@dataclass(frozen=True)
class Principal:
    username: str
    role: str                      # admin | manager | supervisor | employee
    employee_id: str | None = None

    @property
    def is_manager(self) -> bool:
        return self.role in ("admin", "manager")

    @property
    def is_reviewer(self) -> bool:
        """Manager-level OR supervisor: may read the full roster / leave / swap picture (not private employee data)."""
        return self.role in ("admin", "manager", "supervisor")


def get_principal(cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
                  db: Session = Depends(get_db)) -> Principal:
    if not settings.auth_required:
        return Principal("system", "admin")
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_token(cred.credentials)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.scalar(select(AppUser).where(AppUser.username == payload.get("sub")))
    if not user or not user.is_active:  # role is read from the DB, not the token: changes apply immediately
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found or disabled")
    return Principal(user.username, user.role, user.employee_id)


def require_roles(*roles: str):
    allowed = set(roles) | {"admin"}

    def checker(p: Principal = Depends(get_principal)) -> Principal:
        if p.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission for this action")
        return p

    return checker


manager_required = require_roles("manager")
review_required = require_roles("manager", "supervisor")   # read the whole roster, edit drafts; no approve/publish
admin_required = require_roles()


def actor_name(p: Principal, claimed: str | None = None) -> str:
    """Audit actor: the logged-in user. Only the open/demo mode (no auth) trusts a client-supplied name."""
    if settings.auth_required:
        return p.username
    return claimed or p.username
