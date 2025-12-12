param(
  [ValidateSet("status", "up", "down")]
  [string]$Action = "status",
  [ValidateSet("mcp-suite")]
  [string]$Profile = "mcp-suite"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$stackDir = Join-Path $repoRoot "stacks\idc1-stack"

if (-not (Test-Path $stackDir)) {
  throw "idc1-stack directory not found at $stackDir"
}

function Invoke-Compose {
  param(
    [string[]]$Args
  )
  $argList = @("compose") + $Args
  Write-Host "[idc1-stack] docker $($argList -join ' ')"
  $proc = Start-Process -FilePath "docker" -ArgumentList $argList -WorkingDirectory $stackDir -NoNewWindow -Wait -PassThru
  if ($proc.ExitCode -ne 0) {
    throw "docker compose command failed with exit code $($proc.ExitCode)"
  }
}

switch ($Action) {
  "up" {
    Invoke-Compose -Args @("--profile", $Profile, "up", "-d")
  }
  "down" {
    Invoke-Compose -Args @("down")
  }
  default {
    Invoke-Compose -Args @("ps")
  }
}
