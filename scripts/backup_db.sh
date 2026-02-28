#!/usr/bin/env bash
# ============================================================
# Omnipath v2 — Database Backup Script
#
# Features:
#   - pg_dump with compression
#   - Timestamped filenames
#   - Local retention (7 days by default)
#   - Optional S3 upload (set S3_BUCKET env var)
#   - Restore instructions printed on success
#
# Usage:
#   ./scripts/backup_db.sh
#
# Required environment variables:
#   DATABASE_URL   — PostgreSQL connection string
#
# Optional environment variables:
#   S3_BUCKET      — S3 bucket name for remote backup
#   S3_PREFIX      — S3 key prefix (default: omnipath/backups)
#   BACKUP_DIR     — Local backup directory (default: /var/backups/omnipath)
#   RETENTION_DAYS — Days to keep local backups (default: 7)
#
# Built with Pride for Obex Blackvault
# ============================================================

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────
BACKUP_DIR="${BACKUP_DIR:-/var/backups/omnipath}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
S3_BUCKET="${S3_BUCKET:-}"
S3_PREFIX="${S3_PREFIX:-omnipath/backups}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/omnipath_${TIMESTAMP}.sql.gz"
LOG_PREFIX="[backup_db.sh]"

# ── Validate prerequisites ────────────────────────────────────
if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "${LOG_PREFIX} ERROR: DATABASE_URL is not set" >&2
    exit 1
fi

command -v pg_dump >/dev/null 2>&1 || {
    echo "${LOG_PREFIX} ERROR: pg_dump not found — install postgresql-client" >&2
    exit 1
}

command -v gzip >/dev/null 2>&1 || {
    echo "${LOG_PREFIX} ERROR: gzip not found" >&2
    exit 1
}

# ── Create backup directory ───────────────────────────────────
mkdir -p "${BACKUP_DIR}"
echo "${LOG_PREFIX} Starting backup → ${BACKUP_FILE}"

# ── Run pg_dump ───────────────────────────────────────────────
pg_dump \
    --dbname="${DATABASE_URL}" \
    --format=plain \
    --no-password \
    --verbose \
    2>&1 | gzip -9 > "${BACKUP_FILE}"

BACKUP_SIZE=$(du -sh "${BACKUP_FILE}" | cut -f1)
echo "${LOG_PREFIX} Backup complete: ${BACKUP_FILE} (${BACKUP_SIZE})"

# ── Upload to S3 (optional) ───────────────────────────────────
if [[ -n "${S3_BUCKET}" ]]; then
    command -v aws >/dev/null 2>&1 || {
        echo "${LOG_PREFIX} WARNING: aws CLI not found — skipping S3 upload" >&2
    }

    if command -v aws >/dev/null 2>&1; then
        S3_KEY="${S3_PREFIX}/omnipath_${TIMESTAMP}.sql.gz"
        echo "${LOG_PREFIX} Uploading to s3://${S3_BUCKET}/${S3_KEY}"
        aws s3 cp "${BACKUP_FILE}" "s3://${S3_BUCKET}/${S3_KEY}" \
            --storage-class STANDARD_IA \
            --sse AES256
        echo "${LOG_PREFIX} S3 upload complete"
    fi
fi

# ── Prune old local backups ───────────────────────────────────
echo "${LOG_PREFIX} Pruning backups older than ${RETENTION_DAYS} days"
find "${BACKUP_DIR}" -name "omnipath_*.sql.gz" -mtime "+${RETENTION_DAYS}" -delete
REMAINING=$(find "${BACKUP_DIR}" -name "omnipath_*.sql.gz" | wc -l)
echo "${LOG_PREFIX} Retained ${REMAINING} local backup(s)"

# ── Restore instructions ──────────────────────────────────────
cat <<EOF

${LOG_PREFIX} ─────────────────────────────────────────────────
${LOG_PREFIX} RESTORE INSTRUCTIONS
${LOG_PREFIX} ─────────────────────────────────────────────────
${LOG_PREFIX} To restore this backup:
${LOG_PREFIX}
${LOG_PREFIX}   gunzip -c ${BACKUP_FILE} | psql "\$DATABASE_URL"
${LOG_PREFIX}
${LOG_PREFIX} To restore from S3 (if uploaded):
${LOG_PREFIX}
${LOG_PREFIX}   aws s3 cp s3://${S3_BUCKET:-<bucket>}/${S3_PREFIX}/omnipath_${TIMESTAMP}.sql.gz - \\
${LOG_PREFIX}     | gunzip | psql "\$DATABASE_URL"
${LOG_PREFIX} ─────────────────────────────────────────────────
EOF

echo "${LOG_PREFIX} Done."
