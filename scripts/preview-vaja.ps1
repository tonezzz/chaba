param(
  [string]$DevHostBaseUrl = "http://dev-host.pc2:3000",
  [string]$McpVajaHealthUrl = "http://127.0.0.1:7217/health",
  [switch]$SkipDocker,
  [switch]$SkipDevHostCertValidation
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$stackDir = Join-Path $repoRoot "stacks\pc2-worker"
$previewUrl = "$DevHostBaseUrl/test/vaja"
$devHostProxyHealthUrl = "$DevHostBaseUrl/test/vaja/api/health"

function Write-Step {
  param([string]$Message)
  Write-Host "[preview-vaja] $Message"
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
    [int]$DelaySeconds = 5,
    [switch]$SkipCertificateValidation
  )

  $originalCallback = $null
  if ($SkipCertificateValidation) {
    $originalCallback = [System.Net.ServicePointManager]::ServerCertificateValidationCallback
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
  }

  try {
    for ($i = 1; $i -le $Attempts; $i++) {
      try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
          $json = $null
          try {
            $json = $response.Content | ConvertFrom-Json
          } catch {
            # ignore parse errors; we'll return raw content below
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
  } finally {
    if ($SkipCertificateValidation) {
      [System.Net.ServicePointManager]::ServerCertificateValidationCallback = $originalCallback
    }
  }

  throw "Timed out waiting for $ServiceName at $Url"
}

Write-Step "Repository root: $repoRoot"
Test-CommandPrereq -Name "docker" -InstallHint "Install Docker Desktop (WSL2 backend) and ensure it is on PATH."

if (-not $SkipDocker) {
  Write-Step "Bringing up required containers (dev-proxy + mcp-vaja)"
  docker info | Out-Null
  Invoke-DockerCompose -ComposeArgs @("--profile", "mcp-suite", "up", "-d", "dev-proxy", "mcp-vaja")
} else {
  Write-Step "Skipping docker compose bring-up (requested)"
}

Write-Step "Waiting for direct MCP VAJA health"
$mcpHealth = Wait-ForHealth -Url $McpVajaHealthUrl -ServiceName "mcp-vaja"
Write-Step ("mcp-vaja healthy: " + ($mcpHealth | ConvertTo-Json -Depth 5 -Compress))

Write-Step "Validating dev-host proxy"
$proxyHealth = Wait-ForHealth -Url $devHostProxyHealthUrl -ServiceName "dev-host vaja proxy" -SkipCertificateValidation:$SkipDevHostCertValidation
Write-Step ("dev-host proxy healthy: " + ($proxyHealth | ConvertTo-Json -Depth 5 -Compress))

Write-Step "Preview available at $previewUrl"
