param(
  [string]$ComposeFile = "c:\chaba\stacks\pc1-stack\docker-compose.yml",
  [string]$ContainerName = "pc1-caddy"
)

$ErrorActionPreference = "Stop"

$running = docker ps --format "{{.Names}}" | Select-String -SimpleMatch $ContainerName
if (-not $running) {
  throw "Caddy container '$ContainerName' is not running. Start it with: docker-compose --profile mcp-suite -f $ComposeFile up -d caddy"
}

Write-Host "[pc1-caddy] validate Caddyfile" -ForegroundColor Cyan
& docker exec $ContainerName caddy validate --config /etc/caddy/Caddyfile

Write-Host "[pc1-caddy] reload" -ForegroundColor Cyan
& docker exec $ContainerName caddy reload --config /etc/caddy/Caddyfile

Write-Host "[pc1-caddy] done" -ForegroundColor Green
