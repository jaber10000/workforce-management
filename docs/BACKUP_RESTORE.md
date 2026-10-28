# Backup & restore

## What is backed up
The whole PostgreSQL database (employees, leave, roster versions and assignments, audit log, users).
Nothing else needs backing up: the app is stateless, `.env.production` is stored in your password manager.

## Schedule
`docker-compose.prod.yml` runs a `backup` sidecar: every day at `BACKUP_HOUR_UTC` (default 21:00 UTC = 03:00 Dhaka)
it runs `deploy/scripts/backup.sh` -> `./backups/workforce_<UTC timestamp>.dump` + `.sha256`, verifies the dump can be
listed by `pg_restore`, and deletes files older than `BACKUP_RETENTION_DAYS` (14). A failure prints `BACKUP FAILED`
in `docker compose logs backup` - put an alert on that line.

Without Docker use cron:
```
0 21 * * *  DATABASE_URL_LIBPQ=postgresql://user:pw@host/db BACKUP_DIR=/var/backups/workforce /opt/workforce/deploy/scripts/backup.sh >> /var/log/workforce-backup.log 2>&1
```
**Copy the backup folder off the server** (rclone/rsync to other storage, at least weekly). A backup on the same disk
does not survive losing the server.

## Manual backup before an upgrade
`docker compose ... exec backup /scripts/backup.sh`

## Restore (disaster)
1. Stop writers: `docker compose ... stop api`.
2. Create an empty database (or `FORCE=1` to clean an existing one - destructive).
3. `deploy/scripts/restore.sh backups/workforce_<stamp>.dump postgresql://user:pw@host/workforce_roster`
   (checks the checksum, restores in a single transaction, prints row counts and the Alembic revision).
4. Start the api again (`up -d api`; it runs `alembic upgrade head`, so an older dump is migrated forward).
5. Run the smoke test.

## Restore drill (do it once now, then every quarter)
`VERIFY_ONLY=1 deploy/scripts/restore.sh <latest.dump> postgresql://.../scratch_db` - restores into a throw-away database
and prints counts; compare them with production. A backup that has never been restored is only a hope.

Data lost = everything since the last backup (up to 24 h with the default schedule). For lower loss use PostgreSQL
WAL archiving / managed PostgreSQL with point-in-time recovery.
