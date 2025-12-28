param(
  [string]$SourcePath = "C:\chaba\.secrets\pc1.env",
  [string]$Pc1StackEnvPath = "C:\chaba\stacks\pc1-stack\.env",
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

$pc1WorkerLines = Split-PrefixedEnv -Lines $lines -Prefix "PC1W_"
$devHostLines = Split-PrefixedEnv -Lines $lines -Prefix "DEVH_"

if (($pc1WorkerLines.Count -lt 1) -and ($devHostLines.Count -lt 1)) {
  throw "No PC1W_ or DEVH_ entries found in $SourcePath"
}

$pc1StackDir = Split-Path -Parent $Pc1StackEnvPath
$devHostDir = Split-Path -Parent $DevHostEnvPath

New-Item -ItemType Directory -Force -Path $pc1StackDir | Out-Null
New-Item -ItemType Directory -Force -Path $devHostDir | Out-Null

if ($pc1WorkerLines.Count -gt 0) {
  Set-Content -LiteralPath $Pc1StackEnvPath -Value $pc1WorkerLines -Encoding utf8
  Write-Host "[pc1-sync-prefixed-env] Wrote PC1W_ vars -> $Pc1StackEnvPath ($($pc1WorkerLines.Count) lines)"
} else {
  Write-Host "[pc1-sync-prefixed-env] No PC1W_ vars found; skipping $Pc1StackEnvPath"
}

if ($devHostLines.Count -gt 0) {
  Set-Content -LiteralPath $DevHostEnvPath -Value $devHostLines -Encoding utf8
  Write-Host "[pc1-sync-prefixed-env] Wrote DEVH_ vars -> $DevHostEnvPath ($($devHostLines.Count) lines)"
} else {
  Write-Host "[pc1-sync-prefixed-env] No DEVH_ vars found; skipping $DevHostEnvPath"
}

if ($Restart) {
  Write-Host "[pc1-sync-prefixed-env] Restarting pc1-stack (mcp-suite)"
  $proc1 = Start-Process -FilePath "docker" -ArgumentList @("compose", "--profile", "mcp-suite", "up", "-d") -WorkingDirectory "C:\chaba\stacks\pc1-stack" -NoNewWindow -Wait -PassThru
  if ($proc1.ExitCode -ne 0) {
    throw "pc1-stack restart failed (exit $($proc1.ExitCode))"
  }

  Write-Host "[pc1-sync-prefixed-env] Restarting dev-host"
  $proc2 = Start-Process -FilePath "docker" -ArgumentList @("compose", "up", "-d", "--build", "dev-host") -WorkingDirectory "C:\chaba\docker" -NoNewWindow -Wait -PassThru
  if ($proc2.ExitCode -ne 0) {
    throw "dev-host restart failed (exit $($proc2.ExitCode))"
  }

  Write-Host "[pc1-sync-prefixed-env] Core health gate (required services only)"
  $attempts = 12
  $delaySeconds = 3

  $ok1mcp = $false
  for ($i = 1; $i -le $attempts; $i++) {
    try {
      (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:3051/health/ready" -TimeoutSec 10).StatusCode | Out-Null
      $ok1mcp = $true
      break
    } catch {
      Start-Sleep -Seconds $delaySeconds
    }
  }
  if (-not $ok1mcp) {
    throw "core health gate failed: 1mcp not ready on http://127.0.0.1:3051/health/ready"
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

Write-Host "[pc1-sync-prefixed-env] Done"
