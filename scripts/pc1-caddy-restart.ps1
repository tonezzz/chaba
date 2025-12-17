param(
  [string]$ComposeFile = "c:\chaba\stacks\pc1-stack\docker-compose.yml",
  [string]$ContainerName = "pc1-caddy"
)

$ErrorActionPreference = "Stop"

$exists = docker ps -a --format "{{.Names}}" | Select-String -SimpleMatch $ContainerName
if (-not $exists) {
  throw "Container '$ContainerName' not found. Start it with: docker-compose --profile mcp-suite -f $ComposeFile up -d caddy"
}

Write-Host "[pc1-caddy] restart" -ForegroundColor Cyan
& docker restart $ContainerName | Out-Null

Write-Host "[pc1-caddy] validate Caddyfile" -ForegroundColor Cyan
& docker exec $ContainerName caddy validate --config /etc/caddy/Caddyfile

Write-Host "[pc1-caddy] done" -ForegroundColor Green
