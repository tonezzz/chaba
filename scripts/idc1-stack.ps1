param(
  [ValidateSet("status", "up", "down")]
  [string]$Action = "status",
  [ValidateSet("mcp-suite")]
  [string]$Profile = "mcp-suite"
)

$ErrorActionPreference = "Stop"

$idc1Host = if ($env:IDC1_HOST) { $env:IDC1_HOST } else { "idc1.surf-thailand.com" }
$idc1User = if ($env:IDC1_USER) { $env:IDC1_USER } else { "chaba" }
$idc1StackDir = if ($env:IDC1_STACK_DIR) { $env:IDC1_STACK_DIR } else { "/home/chaba/chaba/stacks/idc1-stack" }
$wslDistro = if ($env:IDC1_WSL_DISTRO) { $env:IDC1_WSL_DISTRO } else { "" }
$wslUser = if ($env:IDC1_WSL_USER) { $env:IDC1_WSL_USER } else { "" }

$wslArgs = @()
if ($wslUser) { $wslArgs += @("-u", $wslUser) }
if ($wslDistro) { $wslArgs += @("-d", $wslDistro) }

$composeCmd = switch ($Action) {
  "up" { "docker compose --profile $Profile up -d" }
  "down" { "docker compose down" }
  default { "docker compose ps" }
}

$remote = @"
set -euo pipefail
cd '$idc1StackDir'
echo "[REMOTE] host=$(hostname) user=$(whoami)"
$composeCmd
"@

$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($remote -replace "`r", "")))

$ssh = "/usr/bin/ssh -i ~/.ssh/chaba_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes $idc1User@$idc1Host 'bash -s'"
$bash = "printf %s '$b64' | base64 -d | $ssh"

Write-Host "[idc1-stack] remote via WSL -> SSH -> $idc1User@$idc1Host ($Action)" -ForegroundColor Cyan
& wsl @wslArgs bash -lc $bash
if ($LASTEXITCODE -ne 0) {
  throw "idc1-stack remote command failed with exit code $LASTEXITCODE"
}
