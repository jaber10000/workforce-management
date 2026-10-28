"""Uniform, useful API errors (Step 9). Every error body has `detail` (a readable string) and `request_id`;
validation errors also carry `errors: [{field, message}]`."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging_setup import request_id_var

log = logging.getLogger("workforce")


def _body(detail: str, status: int, **extra) -> JSONResponse:
    return JSONResponse({"detail": detail, "request_id": request_id_var.get(), **extra}, status_code=status)


def _friendly_integrity(exc: IntegrityError) -> str:
    text = str(getattr(exc, "orig", exc)).lower()
    if "employee" in text and "unique" in text or "employees.employee_id" in text or "ix_employees_employee_id" in text:
        return "An employee with this ID already exists"
    if "username" in text:
        return "This username already exists"
    if "application_id" in text:
        return "Duplicate leave application - please retry"
    if "uq_" in text or "unique" in text or "duplicate key" in text:
        return "This record already exists (duplicate request)"
    if "foreign key" in text:
        return "This record refers to data that does not exist"
    return "The change conflicts with existing data"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation(_: Request, exc: RequestValidationError):
        errors = []
        for e in exc.errors():
            loc = [str(x) for x in e.get("loc", ()) if x not in ("body", "query", "path")]
            errors.append({"field": ".".join(loc) or "request", "message": e.get("msg", "invalid value")})
        summary = "; ".join(f"{x['field']}: {x['message']}" for x in errors[:5]) or "Invalid request"
        return _body(summary, 422, errors=errors)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        resp = _body(str(exc.detail), exc.status_code)
        for k, v in (exc.headers or {}).items():
            resp.headers[k] = v
        return resp

    @app.exception_handler(IntegrityError)
    async def integrity(_: Request, exc: IntegrityError):
        log.warning("integrity error: %s", exc.orig)
        return _body(_friendly_integrity(exc), 409)

    @app.exception_handler(OperationalError)
    async def operational(_: Request, exc: OperationalError):
        log.error("database error: %s", exc.orig)
        return _body("The database is temporarily unavailable. Please try again.", 503)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("unhandled exception")
        return _body("Something went wrong on our side. Quote the request_id when reporting it.", 500)
