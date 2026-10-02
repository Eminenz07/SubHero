#!/usr/bin/env bash
# ==============================================================================
# SubHero Automated PostgreSQL Database Backup Script
# ==============================================================================
# Creates a compressed (.sql.gz) backup from the Docker PostgreSQL container,
# verifies integrity, logs the result, and removes backups older than RETENTION_DAYS.
# ==============================================================================

set -eo pipefail

# Configuration
CONTAINER_NAME="subhero_postgres"
DB_USER="subhero"
DB_NAME="subhero_db"
BACKUP_DIR="${BACKUP_DIR:-/home/subhero_admin/backups/postgres}"
RETENTION_DAYS=14
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/subhero_db_${TIMESTAMP}.sql.gz"
LOG_FILE="${BACKUP_DIR}/backup.log"

# Ensure backup directory exists
mkdir -p "${BACKUP_DIR}"

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a "${LOG_FILE}"
}

log "=== Starting database backup for '${DB_NAME}' ==="

# Check if PostgreSQL container is running
if ! docker ps --format '{{.Names}}' | grep -Eq "^${CONTAINER_NAME}\$"; then
    log "ERROR: Container '${CONTAINER_NAME}' is not running! Aborting."
    exit 1
fi

START_TIME=$(date +%s)

# Execute pg_dump inside container and compress with gzip
if docker exec "${CONTAINER_NAME}" pg_dump -U "${DB_USER}" "${DB_NAME}" | gzip -9 > "${BACKUP_FILE}"; then
    FILE_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))

    # Verify backup is non-empty
    if [ ! -s "${BACKUP_FILE}" ]; then
        log "ERROR: Backup file was created but is empty: ${BACKUP_FILE}"
        rm -f "${BACKUP_FILE}"
        exit 1
    fi

    log "SUCCESS: Backup created at ${BACKUP_FILE} (Size: ${FILE_SIZE}, Time: ${DURATION}s)"
else
    log "ERROR: pg_dump command failed!"
    rm -f "${BACKUP_FILE}"
    exit 1
fi

# Prune backups older than RETENTION_DAYS
log "Cleaning up backups older than ${RETENTION_DAYS} days..."
DELETED_COUNT=$(find "${BACKUP_DIR}" -type f -name "subhero_db_*.sql.gz" -mtime +"${RETENTION_DAYS}" | wc -l)
find "${BACKUP_DIR}" -type f -name "subhero_db_*.sql.gz" -mtime +"${RETENTION_DAYS}" -delete
log "Removed ${DELETED_COUNT} expired backup file(s)."

log "=== Backup completed successfully ==="
