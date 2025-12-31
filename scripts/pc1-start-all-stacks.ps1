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
    [Parameter(Mandatory = $true)][string[]]$Args
  )

  $stackDir = Join-Path $repoRoot (Join-Path "stacks" $StackName)
  if (-not (Test-Path $stackDir)) {
    throw "Stack directory not found: $stackDir"
  }

  Initialize-EnvFile -StackDir $stackDir

  Write-Host "[$StackName] docker-compose $($Args -join ' ')"
  Push-Location $stackDir
  try {
    & docker-compose @Args
    if ($LASTEXITCODE -ne 0) {
      throw "docker-compose failed for $StackName (exit $LASTEXITCODE)"
    }
  }
  finally {
    Pop-Location
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
    Invoke-Stack -StackName $stack -Args @("pull")
  }

  if ($stack -eq "pc1-stack") {
    Invoke-Stack -StackName $stack -Args @("--profile", $ComposeProfile, "up", "-d")
  }
  else {
    Invoke-Stack -StackName $stack -Args @("up", "-d")
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
