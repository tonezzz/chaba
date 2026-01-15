param(
  [ValidateSet('up', 'down', 'status', 'pull', 'pull-up', 'restart-service')]
  [string]$Action = 'status',

  [switch]$RemoveVolumes,

  [string]$Profile = '',
  [string]$Services = '',
  [string]$Service = ''
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $repoRoot 'scripts\stack.ps1') -Stack 'pc2-webtops' -Action $Action -RemoveVolumes:$RemoveVolumes -Profile $Profile -Services $Services -Service $Service
