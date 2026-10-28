#!/usr/bin/env bash
# Restore a backup made by backup.sh.
#   ./restore.sh <backup.dump> <target-database-url>            # restores into an EMPTY database
#   VERIFY_ONLY=1 ./restore.sh <backup.dump> <scratch-db-url>   # restore drill: restore + row counts, nothing else
# Never point this at the live database while the API is running - stop the api first (docs/BACKUP_RESTORE.md).
set -euo pipefail
dump="${1:?usage: restore.sh <backup.dump> <target-database-url>}"
target="${2:?target database url (postgresql://...) required}"
[ -f "$dump" ] || { echo "no such file: $dump" >&2; exit 2; }
if [ -f "$dump.sha256" ]; then ( cd "$(dirname "$dump")" && sha256sum -c "$(basename "$dump").sha256" ); fi
pg_restore --list "$dump" > /dev/null
count=$(psql "$target" -Atc "select count(*) from information_schema.tables where table_schema='public'")
if [ "$count" != "0" ] && [ "${FORCE:-0}" != "1" ]; then
  echo "target database is not empty ($count tables). Create a fresh database or set FORCE=1 to --clean it." >&2; exit 3
fi
if [ "${FORCE:-0}" = "1" ]; then clean="--clean --if-exists"; else clean=""; fi
pg_restore --no-owner --single-transaction $clean --dbname="$target" "$dump"
echo "restored. row counts:"
for t in employees leave_applications roster_versions roster_assignments audit_logs app_users; do
  printf '  %-20s %s\n' "$t" "$(psql "$target" -Atc "select count(*) from $t")"
done
echo "alembic revision: $(psql "$target" -Atc 'select version_num from alembic_version' 2>/dev/null || echo 'n/a')"
