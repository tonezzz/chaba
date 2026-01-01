param(
  [ValidateSet('up', 'down', 'status', 'pull', 'pull-up', 'restart-service')]
  [string]$Action = 'status',
  [switch]$RemoveVolumes,
  [string]$Profile = '',
  [string]$Services = '',
  [string]$Service = ''
)

$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot 'stack.ps1'
if (-not (Test-Path $runner)) {
  throw "stack runner not found at $runner"
}

& $runner -Stack 'pc1-devops' -Action $Action -RemoveVolumes:$RemoveVolumes -Profile $Profile -Services $Services -Service $Service
if ($LASTEXITCODE -ne 0) {
  throw "pc1-devops script failed with exit code $LASTEXITCODE"
}
