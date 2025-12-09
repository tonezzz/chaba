param(
    [string]$ConfigPath = "sites/a1-idc1/config/Caddyfile.full",
    [switch]$SkipFormat
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[caddy-validate] $Message"
}

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    throw "ConfigPath cannot be empty."
}

$resolvedPath = Resolve-Path -LiteralPath $ConfigPath -ErrorAction Stop
$configFile = Get-Item -LiteralPath $resolvedPath
$configDir = $configFile.Directory.FullName
$configName = $configFile.Name

Write-Step ("Using config {0}" -f $configFile.FullName)

$dockerImage = "caddy:2"
$volumeSpec = ('{0}:/config' -f $configDir)
$relativeConfig = "/config/$configName"

if (-not $SkipFormat) {
    Write-Step "Running caddy fmt"
    docker run --rm -v $volumeSpec $dockerImage `
        caddy fmt --config $relativeConfig --overwrite | Out-Null
}

Write-Step "Running caddy validate"
docker run --rm -v $volumeSpec $dockerImage `
    caddy validate --config $relativeConfig | Write-Host

Write-Step "Caddy config validated successfully."
