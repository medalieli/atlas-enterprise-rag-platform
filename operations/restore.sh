#!/bin/sh
set -eu
[ $# -eq 1 ] || { echo "usage: restore.sh BACKUP_DIRECTORY" >&2; exit 64; }
src=$1
[ "${ALLOW_DISPOSABLE_RESTORE:-}" = "yes" ] || { echo "refusing restore without ALLOW_DISPOSABLE_RESTORE=yes" >&2; exit 78; }
case "${DATABASE_URL:-}" in *prod*|*production*) echo "refusing production-like restore target" >&2; exit 78;; esac
(cd "$src" && sha256sum -c database.sha256 && sha256sum -c objects.sha256)
started=$(date +%s)
pg_restore --exit-on-error --clean --if-exists --no-owner --no-acl --dbname="$DATABASE_URL" "$src/database.dump"
mkdir -p "${DOCUMENT_STORAGE_PATH:?}"
cp -R "$src/objects"/. "$DOCUMENT_STORAGE_PATH/"
(cd "$DOCUMENT_STORAGE_PATH" && sha256sum -c "$src/objects.sha256")
echo "restore complete: duration_seconds=$(($(date +%s)-started))"
