param(
  [ValidateSet("up", "down", "status", "pull", "pull-up")]
  [string]$Action = "status",
  [string]$Profile = "mcp-suite",
  [string]$Services = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$stackDir = Join-Path $repoRoot (Join-Path "stacks" "pc1-stack")

if (-not (Test-Path $stackDir)) {
  throw "pc1-stack directory not found at $stackDir"
}

function Get-ProfileArgs {
  param(
    [string]$ProfileValue
  )
  if (-not $ProfileValue) {
    return @()
  }
  $profiles = $ProfileValue -split '\s+' | Where-Object { $_ -and $_.Trim() -ne '' }
  $args = @()
  foreach ($p in $profiles) {
    $args += @('--profile', $p)
  }
  return $args
}

function Get-ServiceArgs {
  param(
    [string]$ServicesValue
  )
  if (-not $ServicesValue) {
    return @()
  }
  return ($ServicesValue -split '\s+' | Where-Object { $_ -and $_.Trim() -ne '' })
}

function Invoke-Compose {
  param(
    [string[]]$ComposeArgs
  )
  $argList = @("compose") + $ComposeArgs
  Write-Host "[pc1-stack] docker $($argList -join ' ')"
  Push-Location $stackDir
  try {
    & docker @argList
    if ($LASTEXITCODE -ne 0) {
      throw "docker compose command failed with exit code $LASTEXITCODE"
    }
  }
  finally {
    Pop-Location
  }
}

switch ($Action) {
  "up" {
    $profileArgs = Get-ProfileArgs -ProfileValue $Profile
    $serviceArgs = Get-ServiceArgs -ServicesValue $Services
    Invoke-Compose -ComposeArgs @($profileArgs + @("up", "-d") + $serviceArgs)
  }
  "pull" {
    Invoke-Compose -ComposeArgs @("pull")
  }
  "pull-up" {
    Invoke-Compose -ComposeArgs @("pull")
    $profileArgs = Get-ProfileArgs -ProfileValue $Profile
    $serviceArgs = Get-ServiceArgs -ServicesValue $Services
    Invoke-Compose -ComposeArgs @($profileArgs + @("up", "-d") + $serviceArgs)
  }
  "down" {
    Invoke-Compose -ComposeArgs @("down")
  }
  default {
    Invoke-Compose -ComposeArgs @("ps")
  }
}
