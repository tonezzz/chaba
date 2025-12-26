param(
  [ValidateSet("status", "up", "down")]
  [string]$Action = "status",
  [ValidateSet("mcp-suite")]
  [string]$ComposeProfile = "mcp-suite"
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot '_lib\ssh.ps1')

$idc1Host = if ($env:IDC1_HOST) { $env:IDC1_HOST } else { "idc1.surf-thailand.com" }
$idc1User = if ($env:IDC1_USER) { $env:IDC1_USER } else { "chaba" }
$idc1StackDir = if ($env:IDC1_STACK_DIR) { $env:IDC1_STACK_DIR } else { "/home/chaba/chaba/stacks/idc1-stack" }
$sshKeyWin = if ($env:IDC1_SSH_KEY_WIN) { $env:IDC1_SSH_KEY_WIN } else { (Join-Path $env:USERPROFILE ".ssh\chaba_ed25519") }

$composeCmd = switch ($Action) {
  "up" { "docker compose --profile $ComposeProfile up -d" }
  "down" { "docker compose down" }
  default { "docker compose ps" }
}

$remote = @"
set -euo pipefail
cd '$idc1StackDir'
echo "[REMOTE] host=$(hostname) user=$(whoami)"
$composeCmd
"@

$remoteNoCr = ($remote -replace "`r", "")

Write-Host "[idc1-stack] remote via ssh.exe -> $idc1User@$idc1Host ($Action)" -ForegroundColor Cyan

Invoke-RemoteBashScript -SshUser $idc1User -SshHost $idc1Host -SshKeyPath $sshKeyWin -Script $remoteNoCr | Out-Null
