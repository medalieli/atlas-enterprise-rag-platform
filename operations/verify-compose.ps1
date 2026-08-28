$ErrorActionPreference = 'Stop'
$required = @('PYTHON_IMAGE','UV_IMAGE','NODE_IMAGE','NGINX_IMAGE','POSTGRES_IMAGE','REDIS_IMAGE','OTEL_IMAGE','PROMETHEUS_IMAGE','TEMPO_IMAGE','GRAFANA_IMAGE')
foreach ($name in $required) {
  $value = [Environment]::GetEnvironmentVariable($name)
  if (-not $value -or $value -notmatch '@sha256:[0-9a-f]{64}$') { throw "$name must be pinned by sha256 digest" }
}
docker compose -f compose.yaml -f compose.prod.yaml config --quiet
Write-Output 'Production Compose is valid and base images are digest-pinned.'
