param(
  [int]$Port
)

$ErrorActionPreference = "Stop"

if (-not $PSBoundParameters.ContainsKey("Port") -or $Port -le 0) {
  $envPort = $env:ONE_MCP_PORT
  if ([string]::IsNullOrWhiteSpace($envPort)) {
    $envPort = "3050"
  }
  $Port = [int]$envPort
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$stackDir = Join-Path $repoRoot "stacks\idc1-stack"

if (-not (Test-Path $stackDir)) {
  throw "idc1-stack directory not found at $stackDir"
}

function Invoke-Compose {
  param(
    [string[]]$Args
  )
  $argList = @("compose") + $Args
  Write-Host "[idc1-stack-verify] docker $($argList -join ' ')"
  $proc = Start-Process -FilePath "docker" -ArgumentList $argList -WorkingDirectory $stackDir -NoNewWindow -Wait -PassThru
  if ($proc.ExitCode -ne 0) {
    throw "docker compose command failed with exit code $($proc.ExitCode)"
  }
}

Invoke-Compose -Args @("ps")

$healthUrl = "http://localhost:$Port/health/ready"
$maxAttempts = 5
$delaySeconds = 3
$success = $false

for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
  try {
    Write-Host "[idc1-stack-verify] Checking $healthUrl (attempt $attempt of $maxAttempts)"
    $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 5
    if ($response.StatusCode -eq 200) {
      $success = $true
      break
    } else {
      Write-Warning "[idc1-stack-verify] Unexpected status code $($response.StatusCode)"
    }
  } catch {
    Write-Warning "[idc1-stack-verify] Health check failed: $($_.Exception.Message)"
  }
  Start-Sleep -Seconds $delaySeconds
}

if (-not $success) {
  throw "1mcp-agent health endpoint did not become ready at $healthUrl"
}

Write-Host "[idc1-stack-verify] 1mcp-agent is healthy at $healthUrl"
