#!/usr/bin/env bash
# Daily backup: database dump + uploads. Cron: 0 2 * * * /opt/checklists/backup.sh   (copy this file there)
set -euo pipefail
B=/srv/checklists/backups; D=$(date +%F); cd /opt/checklists/backend
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$B/db-$D.sql.gz"
tar -czf "$B/uploads-$D.tar.gz" -C /srv/checklists uploads
find "$B" -type f -mtime +14 -delete
