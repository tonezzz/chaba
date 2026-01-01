param(
  [ValidateSet('pull-up', 'up')]
  [string]$Action = 'up'
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot

$do = {
  param([string]$scriptName)
  & (Join-Path $repoRoot ('scripts\\' + $scriptName)) -Action $Action
}

& $do 'pc2-devops.ps1'
& $do 'pc2-ai.ps1'
& $do 'pc2-webtops.ps1'
& $do 'pc2-stack.ps1'
