#!/bin/sh
set -eu
umask 077
[ $# -eq 1 ] || { echo "usage: backup.sh OUTPUT_DIRECTORY" >&2; exit 64; }
out=$1
mkdir -p "$out/objects"
started=$(date +%s)
pg_dump --format=custom --compress=9 --no-owner --no-acl --file="$out/database.dump" "$DATABASE_URL"
cp -R "${DOCUMENT_STORAGE_PATH:?}"/. "$out/objects/"
find "$out/objects" -type f -exec sha256sum {} \; | LC_ALL=C sort > "$out/objects.sha256"
sha256sum "$out/database.dump" > "$out/database.sha256"
finished=$(date +%s)
db_bytes=$(wc -c < "$out/database.dump")
object_bytes=$(du -sb "$out/objects" | cut -f1)
printf '{"format":1,"created_utc":"%s","database_bytes":%s,"object_bytes":%s,"duration_seconds":%s}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$db_bytes" "$object_bytes" "$((finished-started))" > "$out/manifest.json"
echo "backup complete: database_bytes=$db_bytes object_bytes=$object_bytes duration_seconds=$((finished-started))"
