#!/bin/sh
set -eu
for name in SESSION_SECRET OIDC_CLIENT_SECRET; do
  eval "file=\${${name}_FILE:-}"
  if [ -n "$file" ]; then
    [ -r "$file" ] || { echo "$name secret file is not readable" >&2; exit 78; }
    value=$(cat "$file")
    [ -n "$value" ] || { echo "$name secret file is empty" >&2; exit 78; }
    export "$name=$value"
  fi
done
case "${APP_ENV:-}" in
  production)
    [ "${DEMO_ROLE_PREVIEW_ENABLED:-false}" != "true" ] || { echo 'Demo role preview is forbidden in production' >&2; exit 78; }
    [ "${APP_BASE_URL#https://}" != "$APP_BASE_URL" ] || { echo 'APP_BASE_URL must use HTTPS' >&2; exit 78; }
    [ ${#SESSION_SECRET} -ge 32 ] || { echo 'SESSION_SECRET must be at least 32 characters' >&2; exit 78; }
    [ -n "${OIDC_CLIENT_ID:-}" ] && [ -n "${OIDC_AUTHORIZATION_URL:-}" ] && [ -n "${OIDC_TOKEN_URL:-}" ] || { echo 'Production OIDC configuration is incomplete' >&2; exit 78; }
    ;;
  development|test) ;;
  *) echo 'APP_ENV must be explicitly set to development, test, or production' >&2; exit 78 ;;
esac
exec "$@"
