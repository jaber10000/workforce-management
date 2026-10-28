from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_SECRET = "dev-only-secret-change-me-0123456789abcdef"


class Settings(BaseSettings):
    app_name: str = "Workforce Roster API"
    api_v1_prefix: str = "/api/v1"
    database_url: str = (
        "postgresql+psycopg://workforce_user:local_dev_password_change_me"
        "@localhost:5432/workforce_roster"
    )
    cors_origins: str = "http://localhost:5173"

    # Roster engine defaults (used when a date has no Daily_Requirement row)
    default_morning_required: int = 55
    default_evening_required: int = 45
    default_night_required: int = 14
    default_min_senior: int = 3
    solver_time_limit_seconds: float = 30.0
    auto_adjust_time_limit_seconds: float = 20.0
    solver_workers: int = 8

    # Production controls
    environment: str = "dev"              # "prod" refuses to start with the default secret key
    auth_required: bool = True            # False = open API with a built-in admin (local demos / tests only)
    secret_key: str = DEFAULT_SECRET
    token_minutes: int = 60 * 8
    require_approval: bool = True         # publish only after a manager approved the draft
    separate_approver: bool = False       # True = the publisher must differ from the approver (four-eyes)
    login_max_failures: int = 5           # per username, per lockout window
    login_lockout_minutes: int = 15

    # Deployment / observability (Step 10)
    log_level: str = "INFO"
    log_json: bool = False                # True = one JSON object per line (for log shippers)
    enable_docs: bool = True              # /docs and /openapi.json; set false in production
    trusted_hosts: str = "*"              # comma list, e.g. "roster.example.com"
    force_https_headers: bool = False     # HSTS etc. (turn on behind the HTTPS proxy)
    sentry_dsn: str = ""                  # optional error monitoring (pip install sentry-sdk)
    slow_request_ms: int = 2000           # requests slower than this are logged as warnings
    # Leave date sanity (Step 9)
    leave_max_backdate_days: int = 30     # employees cannot apply for leave older than this (managers can)
    leave_max_future_days: int = 400
    leave_max_span_days: int = 90         # one application can cover at most this many days

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def trusted_host_list(self) -> list[str]:
        return [h.strip() for h in self.trusted_hosts.split(",") if h.strip()] or ["*"]

    def production_problems(self) -> list[str]:
        """Everything that must be fixed before this configuration may serve real users."""
        bad: list[str] = []
        if self.auth_required is False:
            bad.append("AUTH_REQUIRED must be true")
        if self.secret_key == DEFAULT_SECRET or len(self.secret_key) < 32 or "change-me" in self.secret_key.lower():
            bad.append("SECRET_KEY must be a random value of at least 32 characters")
        if "local_dev_password_change_me" in self.database_url or "CHANGE_ME" in self.database_url:
            bad.append("DATABASE_URL still contains the placeholder password")
        if self.database_url.startswith("sqlite"):
            bad.append("DATABASE_URL must point to PostgreSQL, not SQLite")
        origins = self.cors_origin_list
        if not origins or "*" in origins:
            bad.append("CORS_ORIGINS must list the exact frontend origin(s), not '*'")
        elif any(o.startswith("http://") and "localhost" not in o and "127.0.0.1" not in o for o in origins):
            bad.append("CORS_ORIGINS must use https:// in production")
        if self.enable_docs:
            bad.append("ENABLE_DOCS should be false in production")
        if not self.require_approval:
            bad.append("REQUIRE_APPROVAL must be true")
        return bad

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
