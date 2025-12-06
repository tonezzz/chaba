param(
  [string]$DevHostBaseUrl = "http://dev-host.pc1",
  [switch]$SkipDocker
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$dockerDir = Join-Path $repoRoot "docker"
$baseUrlCandidate = if ([string]::IsNullOrWhiteSpace($DevHostBaseUrl)) { "http://dev-host.pc1" } else { $DevHostBaseUrl }
$TrimmedDevHostBaseUrl = $baseUrlCandidate.Trim().TrimEnd('/')

$services = @(
  @{
    Name = "glama";
    Dir = Join-Path $repoRoot "sites\a1-idc1\api\glama";
    Ecosystem = "ecosystem.config.cjs";
    HealthUrl = "http://127.0.0.1:4020/api/health";
    DevHostHealth = "$TrimmedDevHostBaseUrl/test/chat/api/health";
    PreviewUrl = "$TrimmedDevHostBaseUrl/test/chat/";
  },
  @{
    Name = "agents";
    Dir = Join-Path $repoRoot "sites\a1-idc1\api\agents";
    Ecosystem = "ecosystem.config.cjs";
    HealthUrl = "http://127.0.0.1:4060/api/health";
    DevHostHealth = "$TrimmedDevHostBaseUrl/test/agents/index.html";
    PreviewUrl = "$TrimmedDevHostBaseUrl/test/agents/";
  },
  @{
    Name = "detects";
    Dir = Join-Path $repoRoot "sites\a1-idc1\api\detects";
    Ecosystem = "ecosystem.config.cjs";
    HealthUrl = "http://127.0.0.1:4120/health";
    DevHostHealth = "$TrimmedDevHostBaseUrl/test/detects/api/health";
    PreviewUrl = "$TrimmedDevHostBaseUrl/test/detects/";
  }
)
$testRoot = Join-Path $repoRoot "sites\a1-idc1\test"
$previewUrl = "$TrimmedDevHostBaseUrl/test/"

function Write-Step {
  param([string]$Message)
  Write-Host "[preview-test] $Message"
}

function Test-CommandPrereq {
  param([string]$Name, [string]$InstallHint)
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "Missing required command '$Name'. $InstallHint"
  }
}

function Test-DependenciesReady {
  param([string]$WorkingDir)
  if (-not (Test-Path (Join-Path $WorkingDir "node_modules"))) {
    Write-Step "Installing dependencies in $WorkingDir"
    $install = Start-Process -FilePath "npm" -ArgumentList @("install") -WorkingDirectory $WorkingDir -NoNewWindow -Wait -PassThru
    if ($install.ExitCode -ne 0) {
      throw "npm install failed in $WorkingDir with code $($install.ExitCode)"
    }
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

function Start-Service {
  param($Service)
  Test-Pm2Presence
  Test-DependenciesReady -WorkingDir $Service.Dir

  Push-Location $Service.Dir
  try {
    Write-Step "Starting $($Service.Name) via PM2"
    & pm2 start $Service.Ecosystem --env development --update-env | Out-String | Write-Verbose
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

function Test-TestIndex {
  if (-not (Test-Path (Join-Path $testRoot "index.html"))) {
    throw "sites/a1-idc1/test/index.html is missing. Add the landing page before preview."
  }
}

Write-Step "Repository root: $repoRoot"
Test-CommandPrereq -Name "docker" -InstallHint "Install Docker Desktop and ensure it is on PATH."
Test-CommandPrereq -Name "npm" -InstallHint "Install Node.js 20+ so npm is available."
Test-TestIndex

if (-not $SkipDocker) {
  Write-Step "Checking Docker daemon"
  docker info | Out-Null
  Invoke-DockerCompose -ComposeArgs @("up", "-d", "dev-host")
} else {
  Write-Step "Skipping docker compose bring-up (requested)"
}

foreach ($service in $services) {
  Start-Service -Service $service
  Write-Step "Waiting for $($service.Name) health"
  $health = Wait-ForHealth -Url $service.HealthUrl -ServiceName "$($service.Name) API"
  Write-Step ("$($service.Name) API ready: " + ($health | ConvertTo-Json -Depth 5 -Compress))

  Write-Step "Validating $($service.Name) dev-host endpoint"
  $devHostHealth = Wait-ForHealth -Url $service.DevHostHealth -ServiceName "$($service.Name) dev-host proxy"
  Write-Step ("$($service.Name) proxy ready: " + ($devHostHealth | ConvertTo-Json -Depth 5 -Compress))
}

Write-Step "Validating /test landing page"
$testLanding = Wait-ForHealth -Url $previewUrl -ServiceName "/test landing" -Attempts 6 -DelaySeconds 3
Write-Step ("Test landing ready: " + ($testLanding | ConvertTo-Json -Depth 5 -Compress))

Write-Step "Preview available at $previewUrl"
