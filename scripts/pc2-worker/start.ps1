# Usage: ./start.ps1 base-tools|mcp-suite|gpu|monitoring
param(
    [Parameter(Mandatory=$true)]
    [string]$Profile
)

$composeDir = "C:\chaba\stacks\pc2-worker"
if (!(Test-Path $composeDir)) {
    Write-Error "Compose directory not found: $composeDir"
    exit 1
}

Push-Location $composeDir
try {
    & docker compose --profile $Profile up -d
}
finally {
    Pop-Location
}
