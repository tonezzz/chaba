param(
  [string]$DevHostBaseUrl = "http://dev-host.pc2:3000",
  [string]$ImagenHealthUrl = "http://127.0.0.1:8001/health",
  [string]$ImagenGenerateUrl = "http://127.0.0.1:8001/generate",
  [switch]$SkipDocker,
  [switch]$SkipSmokeTest,
  [int]$SmokeTestSteps = 6,
  [int]$SmokeTestSize = 256,
  [string]$SmokeTestPrompt = "diagnostic render for Imagen preview"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$stackDir = Join-Path $repoRoot "stacks\pc2-worker"
$previewUrl = $ImagenHealthUrl

function Write-Step {
  param([string]$Message)
  Write-Host "[preview-imagen] $Message"
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
  $fullArgs = @("compose") + $ComposeArgs
  $process = Start-Process -FilePath "docker" -ArgumentList $fullArgs -WorkingDirectory $stackDir -NoNewWindow -Wait -PassThru
  if ($process.ExitCode -ne 0) {
    throw "docker compose exited with code $($process.ExitCode)"
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

function Invoke-ImagenSmokeTest {
  param(
    [string]$Url,
    [string]$Prompt,
    [int]$Steps,
    [int]$Size
  )

  $payload = @{
    prompt = $Prompt
    num_inference_steps = $Steps
    width = $Size
    height = $Size
    guidance_scale = 5
  }
  $json = $payload | ConvertTo-Json -Depth 4 -Compress

  Write-Step "Running smoke-test prompt (${Size}x${Size}, ${Steps} steps)"
  try {
    $response = Invoke-WebRequest -Uri $Url -Method Post -ContentType "application/json" -Body $json -UseBasicParsing -TimeoutSec 120
    if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
      $body = $null
      try {
        $body = $response.Content | ConvertFrom-Json
      } catch {}
      $duration = if ($body.duration_ms) { "$($body.duration_ms) ms" } else { "ok" }
      Write-Step "Smoke test succeeded ($duration)"
      return
    }
    throw "HTTP $($response.StatusCode)"
  } catch {
    throw "Smoke test failed: $($_.Exception.Message)"
  }
}

Write-Step "Repository root: $repoRoot"
Test-CommandPrereq -Name "docker" -InstallHint "Install Docker Desktop (WSL2 backend) and ensure it is on PATH."

if (-not $SkipDocker) {
  Write-Step "Bringing up dev-proxy + mcp-imagen-gpu containers"
  docker info | Out-Null
  Invoke-DockerCompose -ComposeArgs @("--profile", "mcp-suite", "up", "-d", "dev-proxy", "mcp-imagen-gpu")
} else {
  Write-Step "Skipping docker compose bring-up (requested)"
}

Write-Step "Waiting for MCP Imagen health"
$imagenHealth = Wait-ForHealth -Url $ImagenHealthUrl -ServiceName "mcp-imagen-gpu"
Write-Step ("mcp-imagen-gpu healthy: " + ($imagenHealth | ConvertTo-Json -Depth 5 -Compress))

if (-not $SkipSmokeTest) {
  Invoke-ImagenSmokeTest -Url $ImagenGenerateUrl -Prompt $SmokeTestPrompt -Steps $SmokeTestSteps -Size $SmokeTestSize
} else {
  Write-Step "Skipping smoke test (requested)"
}

Write-Step "Preview available at $previewUrl"
