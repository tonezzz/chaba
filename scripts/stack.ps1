param(
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^[a-zA-Z0-9-]+$')]
  [string]$Stack,

  [ValidateSet('up', 'down', 'status', 'pull', 'pull-up', 'restart-service')]
  [string]$Action = 'status',

  [string]$Profile = '',
  [string]$Services = '',
  [string]$Service = ''
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$stackDir = Join-Path $repoRoot (Join-Path 'stacks' $Stack)

if (-not (Test-Path $stackDir)) {
  throw "stack directory not found at $stackDir"
}

$composeFile = Join-Path $stackDir 'docker-compose.yml'
if (-not (Test-Path $composeFile)) {
  throw "docker-compose.yml not found at $composeFile"
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
  $argList = @('compose', '-f', $composeFile, '--project-name', $Stack) + $ComposeArgs
  Write-Host "[$Stack] docker $($argList -join ' ')"
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
  'up' {
    $profileArgs = Get-ProfileArgs -ProfileValue $Profile
    $serviceArgs = Get-ServiceArgs -ServicesValue $Services
    Invoke-Compose -ComposeArgs @($profileArgs + @('up', '-d') + $serviceArgs)
  }
  'pull' {
    Invoke-Compose -ComposeArgs @('pull')
  }
  'pull-up' {
    Invoke-Compose -ComposeArgs @('pull')
    $profileArgs = Get-ProfileArgs -ProfileValue $Profile
    $serviceArgs = Get-ServiceArgs -ServicesValue $Services
    Invoke-Compose -ComposeArgs @($profileArgs + @('up', '-d') + $serviceArgs)
  }
  'down' {
    Invoke-Compose -ComposeArgs @('down')
  }
  'restart-service' {
    if (-not $Service) {
      throw 'Missing -Service for -Action restart-service'
    }
    Invoke-Compose -ComposeArgs @('restart', $Service)
  }
  default {
    Invoke-Compose -ComposeArgs @('ps')
  }
}
