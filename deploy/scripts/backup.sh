#!/usr/bin/env bash
# PostgreSQL backup: compressed custom-format dump + checksum + retention.
#   DATABASE_URL_LIBPQ=postgresql://user:pass@host:5432/db  BACKUP_DIR=/backups  RETENTION_DAYS=14  ./backup.sh
# (PGHOST/PGUSER/PGPASSWORD/PGDATABASE also work.) Exit code != 0 on any failure.
set -euo pipefail
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
TARGET="${DATABASE_URL_LIBPQ:-}"
mkdir -p "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
file="$BACKUP_DIR/workforce_${stamp}.dump"
tmp="$file.partial"
if [ -n "$TARGET" ]; then pg_dump --format=custom --no-owner --compress=6 --dbname="$TARGET" --file="$tmp"
else pg_dump --format=custom --no-owner --compress=6 --file="$tmp"; fi
# a dump that pg_restore cannot list is not a backup
pg_restore --list "$tmp" > /dev/null
mv "$tmp" "$file"
( cd "$BACKUP_DIR" && sha256sum "$(basename "$file")" > "$(basename "$file").sha256" )
find "$BACKUP_DIR" -name 'workforce_*.dump*' -mtime +"$RETENTION_DAYS" -delete
echo "$(date -u +%FT%TZ) backup ok: $file ($(du -h "$file" | cut -f1))"
