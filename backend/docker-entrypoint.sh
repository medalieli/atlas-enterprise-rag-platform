#!/bin/sh
set -eu
for name in OPENAI_API_KEY DATABASE_URL POSTGRES_PASSWORD METRICS_BEARER_TOKEN; do
  eval "file=\${${name}_FILE:-}"
  if [ -n "$file" ]; then
    [ -r "$file" ] || { echo "$name secret file is not readable" >&2; exit 78; }
    value=$(cat "$file")
    [ -n "$value" ] || { echo "$name secret file is empty" >&2; exit 78; }
    export "$name=$value"
  fi
done
exec "$@"
