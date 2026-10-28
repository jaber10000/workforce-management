# Deployment guide (Step 10)

Stack: PostgreSQL 16 · FastAPI (one uvicorn worker) · Caddy (automatic HTTPS + static frontend) · backup sidecar.
File: `docker-compose.prod.yml`. Everything below was written for a single Linux server with Docker.

## 1. Configuration (environment variables)
| Variable | Production value |
|---|---|
| `ENVIRONMENT` | `prod` - the API **refuses to start** if any check below fails |
| `SECRET_KEY` | `openssl rand -hex 48` (>= 32 chars, never the default) |
| `DATABASE_URL` | PostgreSQL URL with a real password (no SQLite) |
| `AUTH_REQUIRED` / `REQUIRE_APPROVAL` | `true` / `true` |
| `CORS_ORIGINS` | exactly `https://<your-domain>` (no `*`, no http) |
| `TRUSTED_HOSTS` | `<your-domain>` |
| `ENABLE_DOCS` | `false` |
| `FORCE_HTTPS_HEADERS` | `true` (HSTS) |
| `LOG_JSON` / `LOG_LEVEL` | `true` / `INFO` |
| `SENTRY_DSN` | optional; add `sentry-sdk` to requirements.txt |

Secrets live in `.env.production` (copy `.env.production.example`), never in git.

## 2. First deployment
```bash
cp .env.production.example .env.production      # fill every value
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
# the api container runs `alembic upgrade head` on every start
docker compose --env-file .env.production -f docker-compose.prod.yml exec api \
    env PASSWORD='<strong password>' python -m app.scripts.create_user admin --role admin
docker compose ... exec api env PASSWORD='...' python -m app.scripts.create_user smoke_mgr --role manager
python backend/app/scripts/smoke_test.py https://<domain> --user smoke_mgr --password '...'   # or via -m
```
DNS must point `<domain>` at the server and ports 80/443 must be open - Caddy then gets and renews the
Let's Encrypt certificate by itself. PostgreSQL is on the internal Docker network only (not published).

## 3. Upgrading
1. Take a backup (`deploy/scripts/backup.sh`) - see `BACKUP_RESTORE.md`.
2. `git pull && docker compose ... up -d --build` (migrations run automatically).
3. Run the smoke test. If it fails: restore the backup + previous image.

Existing database created before Alembic (Step 3-5): `alembic upgrade head` is safe - the baseline skips tables
that exist and adds the missing Step 5 columns. **Check first** that no two employees differ only by letter case
(`select lower(employee_id) from employees group by 1 having count(*)>1`) - migration 0002 adds a
case-insensitive unique index and will fail on such data.

## 4. Logging and monitoring
* Logs go to stdout (Docker json-file, rotated 5 x 20 MB). With `LOG_JSON=true` each line is JSON with a `request_id`.
  Every response carries `X-Request-ID`; error bodies include it, so a user report maps to one log line.
* Requests slower than `SLOW_REQUEST_MS` and all 5xx are logged as WARNING.
* `/health` (process up) and `/ready` (database answers) are for load balancers / uptime monitors. Point an external
  uptime check (UptimeRobot, Better Stack...) at `https://<domain>/ready` and alert on failure.
* Optional error tracking: set `SENTRY_DSN`.
* Audit trail (who approved/published/exported what) is in the database: `GET /api/v1/roster/audit-log`.

## 5. Security checklist
- [ ] `ENVIRONMENT=prod` and the API starts (config validated)
- [ ] HTTPS works, `http://` redirects, HSTS header present
- [ ] `/docs` returns 404
- [ ] Default/demo users removed; admin password is unique
- [ ] `.env.production` is not in git; server disk is encrypted or access-restricted
- [ ] Backups run daily **and are copied off the server**; a restore drill has been done
- [ ] Only ports 80/443 (and SSH) are open on the firewall
- [ ] `SEPARATE_APPROVER=true` if the business wants four-eyes publishing

Known limits: login lockout counters are in process memory (hence one worker; multiple workers would each count
separately). Tokens are JWTs valid `TOKEN_MINUTES` (default 8 h); disabling a user takes effect immediately because
the account is re-read on every request, but there is no per-token "log out everywhere" list.

## 6. Final acceptance test (do this on the real server before go-live)
1. `smoke_test` passes (10/10 with credentials).
2. Log in as admin, create manager + employee users.
3. Import employees (`import_employees`), generate a roster, approve, publish.
4. Log in as the employee: sees only the published roster and only own leave/record.
5. Apply for leave -> manager approves -> new draft appears -> approve + publish.
6. Download the four Excel reports; open them in Excel (check version/date on the Info sheet).
7. Run `backup.sh`, then `VERIFY_ONLY=1 restore.sh` into a scratch database.
8. Reboot the server; everything comes back by itself (`restart: unless-stopped`).
