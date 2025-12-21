param(
  [string]$ContainerName = "pc1-caddy",
  [int]$Tail = 200
)

$ErrorActionPreference = "Stop"

Write-Host "[pc1-caddy] logs (tail=$Tail)" -ForegroundColor Cyan

$exists = docker ps -a --format "{{.Names}}" | Select-String -SimpleMatch $ContainerName
if (-not $exists) {
  throw "Container '$ContainerName' not found."
}

docker logs --tail $Tail $ContainerName | Write-Host
