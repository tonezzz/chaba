param(
    [string]$EnvSourcePath = "",
    [string]$GitRef = "main",
    [string]$Profile = "mcp-suite",
    [string]$BaseUrl = "http://1mcp.pc2.vpn:3050",
    [string]$App = "windsurf"
)

$ErrorActionPreference = 'Stop'

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')

Write-Host "[pc2-deploy] Syncing secrets env"
& (Join-Path $repoRoot 'scripts\pc2-worker\sync-env.ps1') -SourcePath $EnvSourcePath

Write-Host "[pc2-deploy] Updating + restarting remote pc2-worker stack"
$env:PC2_GIT_REF = $GitRef
$env:PC2_COMPOSE_PROFILE = $Profile
& (Join-Path $repoRoot 'scripts\pc2-worker\pc2-stack.ps1') -Action up

Write-Host "[pc2-deploy] Running smoke test"
& (Join-Path $repoRoot 'scripts\pc2-worker\smoke-test.ps1') -BaseUrl $BaseUrl -App $App

Write-Host "[pc2-deploy] Done"
