param(
  [string]$SourcePath = "C:\chaba\.secrets\pc2.env",
  [string]$Pc2WorkerEnvPath = "C:\chaba\stacks\pc2-worker\.env",
  [string]$DevHostEnvPath = "C:\chaba\sites\dev-host\.env.dev-host",
  [switch]$Restart
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $SourcePath)) {
  throw "Source env file not found: $SourcePath"
}

$lines = Get-Content -LiteralPath $SourcePath -ErrorAction Stop

function Split-PrefixedEnv {
  param(
    [string[]]$Lines,
    [string]$Prefix
  )

  $out = New-Object System.Collections.Generic.List[string]
  foreach ($line in $Lines) {
    if ($null -eq $line) { continue }
    $trimmed = $line.Trim()
    if ($trimmed.Length -eq 0) { continue }
    if ($trimmed.StartsWith('#')) { continue }
    if ($trimmed -notmatch '^[A-Za-z0-9_]+=') { continue }
    if (-not $trimmed.StartsWith($Prefix)) { continue }

    $out.Add($trimmed.Substring($Prefix.Length))
  }
  return $out.ToArray()
}

$pc2WorkerLines = Split-PrefixedEnv -Lines $lines -Prefix "PC2W_"
$devHostLines = Split-PrefixedEnv -Lines $lines -Prefix "DEVH_"

if (($pc2WorkerLines.Count -lt 1) -and ($devHostLines.Count -lt 1)) {
  throw "No PC2W_ or DEVH_ entries found in $SourcePath"
}

$pc2WorkerDir = Split-Path -Parent $Pc2WorkerEnvPath
$devHostDir = Split-Path -Parent $DevHostEnvPath

New-Item -ItemType Directory -Force -Path $pc2WorkerDir | Out-Null
New-Item -ItemType Directory -Force -Path $devHostDir | Out-Null

if ($pc2WorkerLines.Count -gt 0) {
  Set-Content -LiteralPath $Pc2WorkerEnvPath -Value $pc2WorkerLines -Encoding utf8
  Write-Host "[pc2-sync-prefixed-env] Wrote PC2W_ vars -> $Pc2WorkerEnvPath ($($pc2WorkerLines.Count) lines)"
} else {
  Write-Host "[pc2-sync-prefixed-env] No PC2W_ vars found; skipping $Pc2WorkerEnvPath"
}

if ($devHostLines.Count -gt 0) {
  Set-Content -LiteralPath $DevHostEnvPath -Value $devHostLines -Encoding utf8
  Write-Host "[pc2-sync-prefixed-env] Wrote DEVH_ vars -> $DevHostEnvPath ($($devHostLines.Count) lines)"
} else {
  Write-Host "[pc2-sync-prefixed-env] No DEVH_ vars found; skipping $DevHostEnvPath"
}

if ($Restart) {
  Write-Host "[pc2-sync-prefixed-env] Restarting pc2-worker (mcp-suite)"
  $proc1 = Start-Process -FilePath "docker" -ArgumentList @("compose", "--profile", "mcp-suite", "up", "-d", "--remove-orphans") -WorkingDirectory "C:\chaba\stacks\pc2-worker" -NoNewWindow -Wait -PassThru
  if ($proc1.ExitCode -ne 0) {
    throw "pc2-worker restart failed (exit $($proc1.ExitCode))"
  }

  Write-Host "[pc2-sync-prefixed-env] Restarting dev-host"
  $proc2 = Start-Process -FilePath "docker" -ArgumentList @("compose", "up", "-d", "--build", "--remove-orphans", "dev-host") -WorkingDirectory "C:\chaba\docker" -NoNewWindow -Wait -PassThru
  if ($proc2.ExitCode -ne 0) {
    throw "dev-host restart failed (exit $($proc2.ExitCode))"
  }

  Write-Host "[pc2-sync-prefixed-env] Core health gate (required services only)"
  $attempts = 12
  $delaySeconds = 3

  $ok1mcp = $false
  for ($i = 1; $i -le $attempts; $i++) {
    try {
      (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:3050/health/ready" -TimeoutSec 10).StatusCode | Out-Null
      $ok1mcp = $true
      break
    } catch {
      Start-Sleep -Seconds $delaySeconds
    }
  }
  if (-not $ok1mcp) {
    throw "core health gate failed: 1mcp not ready on http://127.0.0.1:3050/health/ready"
  }

  $devHostOk = $false
  for ($i = 1; $i -le $attempts; $i++) {
    try {
      $health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:3100/api/health" -TimeoutSec 10
      if ($health.status -eq "ok") {
        $devHostOk = $true
        break
      }
      Start-Sleep -Seconds $delaySeconds
    } catch {
      Start-Sleep -Seconds $delaySeconds
    }
  }
  if (-not $devHostOk) {
    throw "core health gate failed: dev-host /api/health did not report status=ok on http://127.0.0.1:3100/api/health"
  }
}

Write-Host "[pc2-sync-prefixed-env] Done"
