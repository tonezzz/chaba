param(
  [switch]$RemoveVolumes
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot

$do = {
  param([string]$scriptName)
  & (Join-Path $repoRoot ('scripts\\' + $scriptName)) -Action 'down' -RemoveVolumes:$RemoveVolumes
}

& $do 'pc2-stack.ps1'
& $do 'pc2-webtops.ps1'
& $do 'pc2-ai.ps1'
& $do 'pc2-devops.ps1'
