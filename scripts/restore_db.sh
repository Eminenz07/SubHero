#!/usr/bin/env bash
# ==============================================================================
# SubHero PostgreSQL Database Restore Script
# ==============================================================================
# Restores a .sql or .sql.gz backup file into the SubHero PostgreSQL container.
#
# Usage:
#   ./scripts/restore_db.sh /path/to/backup.sql.gz
# ==============================================================================

set -eo pipefail

CONTAINER_NAME="subhero_postgres"
DB_USER="subhero"
DB_NAME="subhero_db"

if [ -z "$1" ]; then
    echo "Usage: $0 <path_to_backup_file.sql.gz>"
    echo "Example: $0 ~/backups/postgres/subhero_db_20261002_120000.sql.gz"
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "${BACKUP_FILE}" ]; then
    echo "ERROR: Backup file does not exist: ${BACKUP_FILE}"
    exit 1
fi

echo "=========================================================="
echo "⚠️  WARNING: DATABASE RESTORE"
echo "Target DB: ${DB_NAME} in container '${CONTAINER_NAME}'"
echo "Source:    ${BACKUP_FILE}"
echo "=========================================================="
read -p "Are you sure you want to overwrite '${DB_NAME}'? (type 'yes' to proceed): " CONFIRM

if [ "${CONFIRM}" != "yes" ]; then
    echo "Restore cancelled by user."
    exit 0
fi

echo "[$(date +'%Y-%m-%d %H:%M:%S')] Terminating active connections to ${DB_NAME}..."
docker exec "${CONTAINER_NAME}" psql -U "${DB_USER}" -d postgres -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${DB_NAME}' AND pid <> pg_backend_pid();" || true

echo "[$(date +'%Y-%m-%d %H:%M:%S')] Recreating database ${DB_NAME}..."
docker exec "${CONTAINER_NAME}" psql -U "${DB_USER}" -d postgres -c "DROP DATABASE IF EXISTS ${DB_NAME};"
docker exec "${CONTAINER_NAME}" psql -U "${DB_USER}" -d postgres -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"

echo "[$(date +'%Y-%m-%d %H:%M:%S')] Importing data from ${BACKUP_FILE}..."
if [[ "${BACKUP_FILE}" == *.gz ]]; then
    gzip -dc "${BACKUP_FILE}" | docker exec -i "${CONTAINER_NAME}" psql -U "${DB_USER}" -d "${DB_NAME}"
else
    cat "${BACKUP_FILE}" | docker exec -i "${CONTAINER_NAME}" psql -U "${DB_USER}" -d "${DB_NAME}"
fi

echo "[$(date +'%Y-%m-%d %H:%M:%S')] ✅ Database restore completed successfully!"
