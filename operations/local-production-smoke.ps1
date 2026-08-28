param([ValidateSet('Validate','Up','Down')][string]$Action = 'Validate')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$secretDir = (Resolve-Path (Join-Path $root '.tmp\m15-prod')).Path
$env:API_IMAGE = 'rag-api:14b34fe5b7867fd409279591aadc2a88ddde4827'
$env:FRONTEND_IMAGE = 'rag-frontend:14b34fe5b7867fd409279591aadc2a88ddde4827'
$env:PYTHON_IMAGE = 'python:3.12.14-slim-trixie@sha256:09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217'
$env:UV_IMAGE = 'ghcr.io/astral-sh/uv:0.8.13@sha256:4de5495181a281bc744845b9579acf7b221d6791f99bcc211b9ec13f417c2853'
$env:NODE_IMAGE = 'node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32'
$env:POSTGRES_IMAGE = 'pgvector/pgvector@sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f'
$env:REDIS_IMAGE = 'redis@sha256:987c376c727652f99625c7d205a1cba3cb2c53b92b0b62aade2bd48ee1593232'
$env:NGINX_IMAGE = 'nginx@sha256:42a516af16b852e33b7682d5ef8acbd5d13fe08fecadc7ed98605ba5e3b26ab8'
$env:OTEL_IMAGE = 'otel/opentelemetry-collector-contrib@sha256:45392d534c1edcc809c2d112394029246bc679d2ae5ea7081414a1fc74f2c621'
$env:PROMETHEUS_IMAGE = 'prom/prometheus@sha256:63805ebb8d2b3920190daf1cb14a60871b16fd38bed42b857a3182bc621f4996'
$env:TEMPO_IMAGE = 'grafana/tempo@sha256:0ef775495967cd5d7a6b2e146b6ea695d624803c8db8349fb8ce4164f719f9b7'
$env:GRAFANA_IMAGE = 'grafana/grafana@sha256:a1701c2180249361737a99a01bc770db39381640e4d631825d38ff4535efa47d'
$env:RELEASE_REVISION = '14b34fe5b7867fd409279591aadc2a88ddde4827'
$env:BUILD_DATE = '2026-08-28T11:30:00Z'
$env:APP_BASE_URL = 'https://localhost'
$env:PRODUCTION_HOSTNAME = 'localhost'
$env:OIDC_AUTHORIZATION_URL = 'https://localhost:9444/authorize'
$env:OIDC_TOKEN_URL = 'https://host.docker.internal:9444/token'
$env:OIDC_CLIENT_ID = 'm15-local-client'
$env:AUTH_ISSUER = 'https://host.docker.internal:9444'
$env:AUTH_AUDIENCE = 'production-rag-assistant-api'
$env:AUTH_JWKS_URL = 'https://host.docker.internal:9444/jwks'
$env:AUTH_ENABLED = 'true'
$env:TELEMETRY_ENABLED = 'true'
$env:METRICS_ENABLED = 'true'
$paths = @{
  TLS_CERT_FILE='tls.crt'; TLS_KEY_FILE='tls.key'; LOCAL_CA_CERT_FILE='ca.crt'
  OPENAI_API_KEY_FILE='openai_api_key'; DATABASE_URL_FILE='database_url'
  POSTGRES_PASSWORD_FILE='postgres_password'; SESSION_SECRET_FILE='session_secret'
  OIDC_CLIENT_SECRET_FILE='oidc_client_secret'; METRICS_BEARER_TOKEN_FILE='metrics_bearer_token'
  GRAFANA_ADMIN_PASSWORD_FILE='grafana_admin_password'
}
foreach ($item in $paths.GetEnumerator()) { Set-Item -Path "env:$($item.Key)" -Value (Join-Path $secretDir $item.Value) }
$compose = @('-f','compose.yaml','-f','compose.prod.yaml','-f','compose.local-verification.yaml','--profile','observability')
Push-Location $root
try {
  if ($Action -eq 'Validate') { docker compose @compose config -q; exit $LASTEXITCODE }
  if ($Action -eq 'Down') { docker compose @compose down -v --remove-orphans; exit $LASTEXITCODE }
  docker compose @compose config -q
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
  docker compose @compose up -d --wait --force-recreate postgres redis
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
  docker compose @compose run --rm --no-deps api alembic upgrade head
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
  docker compose @compose up -d --wait --force-recreate
  exit $LASTEXITCODE
} finally { Pop-Location }
