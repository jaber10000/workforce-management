#!/usr/bin/env bash
# Sidecar scheduler used by docker-compose.prod.yml: runs backup.sh every BACKUP_INTERVAL_HOURS (default 24)
# after waiting until BACKUP_HOUR_UTC (default 21 = 03:00 Asia/Dhaka).
set -uo pipefail
HOUR="${BACKUP_HOUR_UTC:-21}"; EVERY="${BACKUP_INTERVAL_HOURS:-24}"
while true; do
  now=$(date -u +%s); next=$(date -u -d "today ${HOUR}:00" +%s)
  [ "$next" -le "$now" ] && next=$(date -u -d "tomorrow ${HOUR}:00" +%s)
  [ "${BACKUP_NOW:-0}" = "1" ] && next=$now && BACKUP_NOW=0
  sleep $(( next - now ))
  /scripts/backup.sh || echo "BACKUP FAILED $(date -u +%FT%TZ)" >&2
  sleep $(( EVERY * 3600 - 60 ))
done
