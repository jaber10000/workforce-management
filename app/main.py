from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.auth import router as auth_router
from app.api.routes.employees import router as employees_router
from app.api.routes.teams import router as teams_router
from app.api.routes.me import router as me_router
from app.api.routes.messages import router as messages_router
from app.api.routes.kpi import router as kpi_router
from app.api.routes.leaves import router as leaves_router
from app.api.routes.roster import router as roster_router
from app.api.routes.swaps import router as swaps_router
from app.core.config import DEFAULT_SECRET, settings
from app.db.session import Base, engine
from app import models  # noqa: F401 — registers SQLAlchemy models
import logging
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.routes.exports import router as exports_router
from app.api.routes.imports import router as imports_router
from app.core.errors import install_error_handlers
from app.core.logging_setup import install_middleware, setup_logging, setup_sentry
from sqlalchemy.orm import Session

from app.db.session import get_db

log = logging.getLogger("workforce")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    if setup_sentry():
        log.info("Sentry error monitoring enabled")
    if settings.environment == "prod":
        problems = settings.production_problems()
        if problems:
            raise RuntimeError("Refusing to start in production: " + "; ".join(problems))
    elif settings.auth_required and settings.secret_key == DEFAULT_SECRET:
        log.warning("Using the default SECRET_KEY - fine for local dev, never for production")
    if not settings.auth_required:
        log.warning("AUTH_REQUIRED=false: the API is open to everyone (demo / test mode)")
    if settings.environment != "prod":
        Base.metadata.create_all(bind=engine)  # dev convenience; production uses `alembic upgrade head`
    log.info("started env=%s version=%s", settings.environment, APP_VERSION)
    yield


APP_VERSION = "1.0.0"

app = FastAPI(title=settings.app_name, version=APP_VERSION, lifespan=lifespan,
              docs_url="/docs" if settings.enable_docs else None,
              redoc_url=None, openapi_url="/openapi.json" if settings.enable_docs else None)
install_error_handlers(app)
if settings.trusted_host_list != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["Content-Disposition", "X-Request-ID"],
)
install_middleware(app)  # added last = outermost: request id + logging + security headers wrap everything

app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(swaps_router, prefix=settings.api_v1_prefix)
app.include_router(employees_router, prefix=settings.api_v1_prefix)
app.include_router(teams_router, prefix=settings.api_v1_prefix)
app.include_router(me_router, prefix=settings.api_v1_prefix)
app.include_router(messages_router, prefix=settings.api_v1_prefix)
app.include_router(kpi_router, prefix=settings.api_v1_prefix)
app.include_router(leaves_router, prefix=settings.api_v1_prefix)
app.include_router(roster_router, prefix=settings.api_v1_prefix)
app.include_router(exports_router, prefix=settings.api_v1_prefix)
app.include_router(imports_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "version": APP_VERSION}


@app.get("/ready", tags=["Health"])
def ready(db: Session = Depends(get_db)):
    """Readiness probe: the database must answer."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(503, "database unavailable")
    return {"status": "ready"}
