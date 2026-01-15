# Usage: ./stop.ps1 [profile]
param(
    [string]$Profile = ""
)

$composeDir = "C:\chaba\stacks\pc2-worker"
if (!(Test-Path $composeDir)) {
    Write-Error "Compose directory not found: $composeDir"
    exit 1
}

Push-Location $composeDir
try {
    if ($Profile) {
        & docker compose --profile $Profile down
    } else {
        & docker compose down
    }
}
finally {
    Pop-Location
}
