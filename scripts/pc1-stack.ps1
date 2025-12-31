param(
  [ValidateSet("up", "down", "status", "pull", "pull-up")]
  [string]$Action = "status",
  [string]$Profile = "mcp-suite",
  [string]$Services = ""
)

$ErrorActionPreference = "Stop"
$runner = Join-Path $PSScriptRoot 'stack.ps1'
if (-not (Test-Path $runner)) {
  throw "stack runner not found at $runner"
}

& $runner -Stack 'pc1-stack' -Action $Action -Profile $Profile -Services $Services
if ($LASTEXITCODE -ne 0) {
  throw "pc1-stack wrapper failed with exit code $LASTEXITCODE"
}
