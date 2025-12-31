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
    [Parameter(Mandatory = $true)][string[]]$Args
  )

  $stackDir = Join-Path $repoRoot (Join-Path "stacks" $StackName)
  if (-not (Test-Path $stackDir)) {
    throw "Stack directory not found: $stackDir"
  }

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
  $composeArgs = @("down")

  # Mirror start script behavior (pc1-stack is started with profiles)
  if ($stack -eq "pc1-stack") {
    $composeArgs = @("--profile", $ComposeProfile, "down")
  }

  if ($RemoveVolumes) {
    $composeArgs += "-v"
  }

  Invoke-Stack -StackName $stack -Args $composeArgs
}

Write-Host "[pc1-stop-all-stacks] Done."
