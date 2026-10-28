"""Logging, request ids, security headers and optional Sentry (Step 10)."""
import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

from app.core.config import settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
log = logging.getLogger("workforce")


class _Formatter(logging.Formatter):
    def __init__(self, as_json: bool):
        super().__init__("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s")
        self.as_json = as_json

    def format(self, record: logging.LogRecord) -> str:
        record.request_id = request_id_var.get()
        if not self.as_json:
            return super().format(record)
        out = {"time": self.formatTime(record), "level": record.levelname, "logger": record.name,
               "request_id": record.request_id, "message": record.getMessage()}
        if record.exc_info:
            out["exception"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_Formatter(settings.log_json))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level.upper())
    logging.getLogger("uvicorn.access").disabled = True  # replaced by our request log (has user + request id)


def setup_sentry() -> bool:
    if not settings.sentry_dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        log.warning("SENTRY_DSN is set but sentry-sdk is not installed (pip install sentry-sdk)")
        return False
    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment, send_default_pii=False,
                    traces_sample_rate=0.0)
    return True


def install_middleware(app) -> None:
    from fastapi.responses import JSONResponse

    @app.middleware("http")
    async def request_context(request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)
        started = time.perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception:
                log.exception("unhandled error %s %s", request.method, request.url.path)
                response = JSONResponse(
                    {"detail": "Something went wrong on our side. Quote the request_id when reporting it.",
                     "request_id": rid}, status_code=500)
            response.headers["X-Request-ID"] = rid
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers.setdefault("Cache-Control", "no-store")
            if settings.force_https_headers:
                response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            ms = (time.perf_counter() - started) * 1000
            if request.url.path not in ("/health", "/ready"):
                level = logging.WARNING if (response.status_code >= 500 or ms > settings.slow_request_ms) else logging.INFO
                log.log(level, "%s %s -> %s in %.0f ms", request.method, request.url.path, response.status_code, ms)
            return response
        finally:
            request_id_var.reset(token)
