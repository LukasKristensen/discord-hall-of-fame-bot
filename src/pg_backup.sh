#!/usr/bin/env bash
set -euo pipefail

# Load environment variables
ENV_FILE="/home/lukas/hall-of-fame/.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
else
  echo "ERROR: .env file not found"
  exit 1
fi

BACKUP_DIR="/var/backups/postgres"
DB_NAME="halloffame"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M")
FILE="$BACKUP_DIR/$DB_NAME-$TIMESTAMP.sql.gz"

# Ensure password exists
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD not set}"

export PGPASSWORD="$POSTGRES_PASSWORD"

pg_dump -U pgbackup "$DB_NAME" | gzip > "$FILE"

unset PGPASSWORD

# Upload to Google Drive (encrypted)
rclone copy "$FILE" drivecrypt:postgres \
  --drive-chunk-size 64M \
  --tpslimit 5 \
  --tpslimit-burst 5

# Local retention (30 days)
find "$BACKUP_DIR" -type f -mtime +30 -delete
