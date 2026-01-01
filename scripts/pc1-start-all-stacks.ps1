param(
  [switch]$Pull,
  [switch]$SmokeTest,
  [switch]$SkipDeka,
  [string]$ComposeProfile = "mcp-suite"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

function Initialize-EnvFile {
  param(
    [Parameter(Mandatory = $true)][string]$StackDir
  )

  $envPath = Join-Path $StackDir ".env"
  if (Test-Path $envPath) {
    return
  }

  $examplePath = Join-Path $StackDir ".env.example"
  if (-not (Test-Path $examplePath)) {
    throw "Missing $envPath and no .env.example found at $examplePath"
  }

  Copy-Item -Path $examplePath -Destination $envPath -Force
  Write-Host "[env] Created $envPath from .env.example"
}

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

  Initialize-EnvFile -StackDir $stackDir

  $wrapper = Join-Path $repoRoot (Join-Path "scripts" ("$StackName.ps1"))
  if (-not (Test-Path $wrapper)) {
    throw "Stack wrapper script not found: $wrapper"
  }

  Write-Host "[$StackName] $wrapper -Action $Action"
  if ($Profile) {
    & $wrapper -Action $Action -Profile $Profile
  } else {
    & $wrapper -Action $Action
  }
  if ($LASTEXITCODE -ne 0) {
    throw "Stack action failed for $StackName (exit $LASTEXITCODE)"
  }
}

$startOrder = @(
  "pc1-db",
  "pc1-gpu",
  "pc1-ai",
  "pc1-devops",
  "pc1-web",
  "pc1-stack"
)

if (-not $SkipDeka) {
  $startOrder += "pc1-deka"
}

foreach ($stack in $startOrder) {
  if ($Pull) {
    Invoke-Stack -StackName $stack -Action 'pull'
  }

  if ($stack -eq "pc1-stack") {
    Invoke-Stack -StackName $stack -Action 'up' -Profile $ComposeProfile
  }
  else {
    Invoke-Stack -StackName $stack -Action 'up'
  }
}

if ($SmokeTest) {
  $smoke = Join-Path $repoRoot (Join-Path "scripts" "pc1-mcp-smoke-test.ps1")
  if (-not (Test-Path $smoke)) {
    throw "Smoke test script not found: $smoke"
  }
  Write-Host "[smoke-test] Running: $smoke"
  & $smoke
  if ($LASTEXITCODE -ne 0) {
    throw "Smoke test failed (exit $LASTEXITCODE)"
  }
}

Write-Host "[pc1-start-all-stacks] Done."
