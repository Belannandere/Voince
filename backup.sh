#!/bin/bash
# Voince SQLite backup — runs daily, keeps 14 days.
set -euo pipefail

BACKUP_DIR=/srv/voince/backups
DB=/srv/voince/invoices.db
DATE=$(date +%Y-%m-%d_%H-%M)

mkdir -p "$BACKUP_DIR"
sqlite3 "$DB" ".backup '$BACKUP_DIR/invoices_$DATE.db'"
gzip -f "$BACKUP_DIR/invoices_$DATE.db"

# Keep only last 14 backups
ls -1t "$BACKUP_DIR"/invoices_*.db.gz 2>/dev/null | tail -n +15 | xargs -r rm

echo "[$(date)] Backup done: invoices_$DATE.db.gz"
