param(
  [string]$EnvFile = "C:\chaba\.secrets\tony\default.env"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $EnvFile)) {
  throw "Env file not found: $EnvFile"
}

Get-Content $EnvFile |
  Where-Object { $_ -and $_ -notmatch '^\s*#' } |
  ForEach-Object {
    $parts = $_ -split '=', 2
    $k = $parts[0].Trim()
    $v = ""
    if ($parts.Count -gt 1) {
      $v = $parts[1].Trim()
    }
    if ($k) {
      [Environment]::SetEnvironmentVariable($k, $v, 'Process')
    }
  }

if ([string]::IsNullOrWhiteSpace($env:GITHUB_PERSONAL_ACCESS_TOKEN)) {
  Write-Host "EMPTY"
  exit 1
}

Write-Host "SET"

# Verify docker passthrough without printing token
& docker run --rm -e GITHUB_PERSONAL_ACCESS_TOKEN alpine:3.20 sh -lc 'echo token_length=${#GITHUB_PERSONAL_ACCESS_TOKEN}'
if ($LASTEXITCODE -ne 0) {
  throw "docker verification failed with exit code $LASTEXITCODE"
}
