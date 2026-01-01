param(
  [switch]$RemoveVolumes,
  [switch]$SkipDeka,
  [string]$ComposeProfile = "mcp-suite"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

function Invoke-Stack {
  param(
    [Parameter(Mandatory = $true)][string]$StackName,
    [Parameter(Mandatory = $true)][string]$Action,
    [string]$Profile = ''
  )

  $stackDir = Join-Path $repoRoot (Join-Path "stacks" $StackName)
  if (-not (Test-Path $stackDir)) {
    throw "Stack directory not found: $stackDir"
  }

  $wrapper = Join-Path $repoRoot (Join-Path "scripts" ("$StackName.ps1"))
  if (-not (Test-Path $wrapper)) {
    throw "Stack wrapper script not found: $wrapper"
  }

  Write-Host "[$StackName] $wrapper -Action $Action"
  if ($Profile) {
    & $wrapper -Action $Action -Profile $Profile -RemoveVolumes:$RemoveVolumes
  } else {
    & $wrapper -Action $Action -RemoveVolumes:$RemoveVolumes
  }
  if ($LASTEXITCODE -ne 0) {
    throw "Stack action failed for $StackName (exit $LASTEXITCODE)"
  }
}

# Stop in reverse dependency order
$stopOrder = @(
  "pc1-stack",
  "pc1-web",
  "pc1-devops",
  "pc1-ai",
  "pc1-gpu",
  "pc1-db"
)

if (-not $SkipDeka) {
  $stopOrder = @("pc1-deka") + $stopOrder
}

foreach ($stack in $stopOrder) {
  if ($stack -eq "pc1-stack") {
    Invoke-Stack -StackName $stack -Action 'down' -Profile $ComposeProfile
  } else {
    Invoke-Stack -StackName $stack -Action 'down'
  }
}

Write-Host "[pc1-stop-all-stacks] Done."
