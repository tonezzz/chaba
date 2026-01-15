param(
  [string]$DevHostBaseUrl = "http://dev-host.pc1:3000",
  [switch]$SkipDocker
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$dockerDir = Join-Path $repoRoot "docker"
$detectsDir = Join-Path $repoRoot "sites\a1-idc1\api\detects"
$detectsHealthUrl = "http://127.0.0.1:4120/health"
$devHostHealthUrl = "$DevHostBaseUrl/test/detects/api/health"
$previewUrl = "$DevHostBaseUrl/test/detects/"

function Write-Step {
  param([string]$Message)
  Write-Host "[preview-detects] $Message"
}

function Test-CommandPrereq {
  param([string]$Name, [string]$InstallHint)
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "Missing required command '$Name'. $InstallHint"
  }
}

function Invoke-DockerCompose {
  param([string[]]$ComposeArgs)
  Write-Step "docker compose $($ComposeArgs -join ' ')"
  $composeArgs = @("compose") + $ComposeArgs
  $compose = Start-Process -FilePath "docker" -ArgumentList $composeArgs -WorkingDirectory $dockerDir -NoNewWindow -Wait -PassThru
  if ($compose.ExitCode -ne 0) {
    throw "docker compose exited with code $($compose.ExitCode)"
  }
}

function Test-Pm2Presence {
  if (Get-Command pm2 -ErrorAction SilentlyContinue) {
    return
  }
  Write-Step "pm2 not found; installing globally via npm"
  $npm = Start-Process -FilePath "npm" -ArgumentList @("install", "-g", "pm2") -WorkingDirectory $repoRoot -NoNewWindow -Wait -PassThru
  if ($npm.ExitCode -ne 0) {
    throw "npm install -g pm2 failed with code $($npm.ExitCode)"
  }
}

function Start-DetectsApi {
  Test-Pm2Presence
  Push-Location $detectsDir
  try {
    if (-not (Test-Path (Join-Path $detectsDir "node_modules"))) {
      Write-Step "Installing detects dependencies"
      $install = Start-Process -FilePath "npm" -ArgumentList @("install") -NoNewWindow -Wait -PassThru
      if ($install.ExitCode -ne 0) {
        throw "npm install failed with code $($install.ExitCode)"
      }
    }

    Write-Step "Starting detects API via PM2"
    & pm2 start "ecosystem.config.cjs" --env development --update-env | Out-String | Write-Verbose
    & pm2 save | Out-String | Write-Verbose
  } finally {
    Pop-Location
  }
}

function Wait-ForHealth {
  param(
    [string]$Url,
    [string]$ServiceName,
    [int]$Attempts = 12,
    [int]$DelaySeconds = 5
  )

  for ($i = 1; $i -le $Attempts; $i++) {
    try {
      $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
      if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
        $json = $null
        try {
          $json = $response.Content | ConvertFrom-Json
        } catch {
          # ignore parse failure; still return raw body
        }
        if ($null -ne $json) {
          return $json
        }
        return $response.Content
      }
    } catch {
      Write-Verbose $_
    }
    if ($i -lt $Attempts) {
      Start-Sleep -Seconds $DelaySeconds
    }
  }

  throw "Timed out waiting for $ServiceName at $Url"
}

Write-Step "Repository root: $repoRoot"
Test-CommandPrereq -Name "docker" -InstallHint "Install Docker Desktop and ensure it is on PATH."
Test-CommandPrereq -Name "npm" -InstallHint "Install Node.js 20+ so npm is available."

if (-not $SkipDocker) {
  Write-Step "Checking Docker daemon"
  docker info | Out-Null
  Invoke-DockerCompose -ComposeArgs @("up", "-d", "dev-host")
} else {
  Write-Step "Skipping docker compose bring-up (requested)"
}

Start-DetectsApi

Write-Step "Waiting for detects API health"
$detectsHealth = Wait-ForHealth -Url $detectsHealthUrl -ServiceName "detects API"
Write-Step ("Detects API ready: " + ($detectsHealth | ConvertTo-Json -Depth 5 -Compress))

Write-Step "Validating dev-host proxy"
$devHostHealth = Wait-ForHealth -Url $devHostHealthUrl -ServiceName "dev-host detects proxy"
Write-Step ("Dev-host proxy ready: " + ($devHostHealth | ConvertTo-Json -Depth 5 -Compress))

Write-Step "Preview available at $previewUrl"
