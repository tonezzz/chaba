param(
  [string]$EnvFile = "C:\chaba\.secrets\tony\default.env"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $EnvFile)) {
  throw "Env file not found: $EnvFile"
}

$line = Get-Content $EnvFile | Where-Object { $_ -match '^\s*GITHUB_PERSONAL_ACCESS_TOKEN\s*=' } | Select-Object -First 1
if (-not $line) {
  throw "GITHUB_PERSONAL_ACCESS_TOKEN not found in $EnvFile"
}

$parts = $line -split '=', 2
$value = ""
if ($parts.Count -gt 1) {
  $value = $parts[1].Trim()
}

if ([string]::IsNullOrWhiteSpace($value)) {
  throw "GITHUB_PERSONAL_ACCESS_TOKEN is empty in $EnvFile"
}

[Environment]::SetEnvironmentVariable('GITHUB_PERSONAL_ACCESS_TOKEN', $value, 'User')
Write-Host "Set GITHUB_PERSONAL_ACCESS_TOKEN at User scope (value not shown)." -ForegroundColor Green
