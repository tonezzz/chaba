param(
  [string]$ContainerName = "pc1-caddy"
)

$ErrorActionPreference = "Stop"

Write-Host "[pc1-caddy] status" -ForegroundColor Cyan

$exists = docker ps -a --format "{{.Names}}" | Select-String -SimpleMatch $ContainerName
if (-not $exists) {
  throw "Container '$ContainerName' not found."
}

docker ps -a --filter "name=^/${ContainerName}$" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | Write-Host
