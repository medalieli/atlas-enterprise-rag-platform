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
    [ "${LOCAL_SYNTHETIC_OWNER_ENABLED:-false}" != "true" ] || { echo 'Local synthetic Owner is forbidden in production' >&2; exit 78; }
    [ "${DEMO_ROLE_PREVIEW_ENABLED:-false}" != "true" ] || { echo 'Demo role preview is forbidden in production' >&2; exit 78; }
    [ "${APP_BASE_URL#https://}" != "$APP_BASE_URL" ] || { echo 'APP_BASE_URL must use HTTPS' >&2; exit 78; }
    [ ${#SESSION_SECRET} -ge 32 ] || { echo 'SESSION_SECRET must be at least 32 characters' >&2; exit 78; }
    [ -n "${OIDC_CLIENT_ID:-}" ] && [ -n "${OIDC_AUTHORIZATION_URL:-}" ] && [ -n "${OIDC_TOKEN_URL:-}" ] || { echo 'Production OIDC configuration is incomplete' >&2; exit 78; }
    case "${OIDC_AUTHORIZATION_URL}" in https://*) ;; *) echo 'Production authorization endpoint must use HTTPS' >&2; exit 78 ;; esac
    case "${OIDC_TOKEN_URL}" in https://*) ;; *) echo 'Production token endpoint must use HTTPS' >&2; exit 78 ;; esac
    ;;
  development|test) ;;
  *) echo 'APP_ENV must be explicitly set to development, test, or production' >&2; exit 78 ;;
esac
loopback_origin=false
case "${APP_BASE_URL:-}" in
  http://localhost|http://localhost:*|https://localhost|https://localhost:*|http://127.0.0.1|http://127.0.0.1:*|https://127.0.0.1|https://127.0.0.1:*) loopback_origin=true ;;
esac
if [ "$loopback_origin" != "true" ]; then
  [ "${LOCAL_SYNTHETIC_OWNER_ENABLED:-false}" != "true" ] || { echo 'Local synthetic Owner is forbidden for external origins' >&2; exit 78; }
  [ -n "${OIDC_CLIENT_ID:-}" ] && [ -n "${OIDC_AUTHORIZATION_URL:-}" ] && [ -n "${OIDC_TOKEN_URL:-}" ] || { echo 'External origins require complete OIDC configuration' >&2; exit 78; }
  case "${OIDC_AUTHORIZATION_URL}" in https://*) ;; *) echo 'External authorization endpoint must use HTTPS' >&2; exit 78 ;; esac
  case "${OIDC_TOKEN_URL}" in https://*) ;; *) echo 'External token endpoint must use HTTPS' >&2; exit 78 ;; esac
fi
if [ "${LOCAL_SYNTHETIC_OWNER_ENABLED:-false}" = "true" ]; then
  [ "${APP_ENV:-}" = "development" ] || { echo 'Local synthetic Owner requires APP_ENV=development' >&2; exit 78; }
  [ "$loopback_origin" = "true" ] || { echo 'Local synthetic Owner requires a loopback APP_BASE_URL' >&2; exit 78; }
  case "${OIDC_AUTHORIZATION_URL:-}" in
    http://localhost/*|http://localhost:*/*|https://localhost/*|https://localhost:*/*|http://127.0.0.1/*|http://127.0.0.1:*/*|https://127.0.0.1/*|https://127.0.0.1:*/*) ;;
    *) echo 'Local synthetic Owner requires a loopback authorization endpoint' >&2; exit 78 ;;
  esac
fi
exec "$@"
