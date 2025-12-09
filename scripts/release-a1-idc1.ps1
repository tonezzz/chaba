param(
    [switch]$SkipValidate,
    [switch]$SkipDeploy,
    [switch]$SkipReload,
    [switch]$SkipVerify,
    [switch]$DryRun,
    [string]$Project = 'detects-test',
    [string]$SshKeyPath
)

$ErrorActionPreference = 'Stop'

function Write-Step {
    param([string]$Message)
    Write-Host "[release-a1-idc1] $Message"
}

function Invoke-Step {
    param(
        [string]$Name,
        [ScriptBlock]$Action
    )

    Write-Step $Name
    if ($DryRun) {
        Write-Step '- (dry-run) skipped'
        return
    }

    try {
        & $Action
        if ($LASTEXITCODE -ne 0) {
            throw "$Name failed with exit code $LASTEXITCODE"
        }
    } catch {
        throw "$Name failed: $($_.Exception.Message)"
    }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$scriptsRoot = Join-Path $repoRoot 'scripts'

function Invoke-WslBash {
    param([string]$Script)
    if ([string]::IsNullOrWhiteSpace($Script)) {
        return ""
    }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Script)
    $base64 = [Convert]::ToBase64String($bytes)
    $escaped = $base64 -replace "'", "'""'""'"
    $command = "base64 -d <<< '$escaped' | bash"
    return & wsl.exe bash -lc $command
}

function Get-WslPath {
    param([string]$WindowsPath)
    if ([string]::IsNullOrWhiteSpace($WindowsPath)) {
        throw 'WindowsPath is required for Get-WslPath.'
    }
    $raw = & wsl.exe wslpath -a -- "`"$WindowsPath`"" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) {
        throw "Failed to convert path '$WindowsPath' to WSL format. Ensure WSL is installed."
    }
    return $raw.Trim()
}

function ConvertTo-ShellLiteral {
    param([string]$Value)
    if ($null -eq $Value) { return "''" }
    $escaped = $Value -replace "'", "'""'""'"
    return "'$escaped'"
}

function Invoke-WslScript {
    param(
        [string]$Description,
        [string[]]$Commands,
        [hashtable]$EnvVars
    )
    $lines = @()
    if ($EnvVars) {
        foreach ($entry in $EnvVars.GetEnumerator()) {
            $value = [string]$entry.Value
            $literal = ConvertTo-ShellLiteral $value
            $lines += "export $($entry.Key)=$literal"
        }
    }
    $lines += $Commands
    $payload = ($lines -join '; ')
    Invoke-Step $Description {
        Invoke-WslBash -Script $payload | Write-Host
    }
}

function Prepare-WslKeyPath {
    param(
        [string]$KeyPath,
        [bool]$IsAlreadyWsl
    )

    $wslPath = if ($IsAlreadyWsl) { $KeyPath } else { Get-WslPath $KeyPath }
    $needsCopy = $wslPath -like '/mnt/*'
    if (-not $needsCopy) {
        $chmodCmd = "chmod 600 $(ConvertTo-ShellLiteral $wslPath) 2>/dev/null || true"
        Invoke-WslBash -Script $chmodCmd | Out-Null
        return [PSCustomObject]@{
            Path = $wslPath
            Cleanup = $null
        }
    }

    $safePath = "/tmp/a1-release-key-$([Guid]::NewGuid().ToString('N'))"
    $origLiteral = ConvertTo-ShellLiteral $wslPath
    $tmpLiteral = ConvertTo-ShellLiteral $safePath
    $scriptLines = @(
        'set -euo pipefail',
        "orig=$origLiteral",
        "tmp=$tmpLiteral",
        'mkdir -p "$(dirname "$tmp")"',
        'cp "$orig" "$tmp"',
        'chmod 600 "$tmp"',
        'echo "$tmp"'
    )
    $script = $scriptLines -join '; '
    $prepared = Invoke-WslBash -Script $script
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($prepared)) {
        throw "Failed to prepare SSH key for WSL usage."
    }
    $preparedPath = $prepared.Trim().Split("`n")[-1].Trim()
    return [PSCustomObject]@{
        Path = $preparedPath
        Cleanup = "rm -f $(ConvertTo-ShellLiteral $preparedPath)"
    }
}

$wslRepoPath = Get-WslPath $repoRoot
$deployScript = './scripts/deploy-a1-idc1.sh'
$verifyScript = './scripts/verify-a1-idc1-test.sh'
$targetUrl = $env:A1_IDC1_TEST_URL
if ([string]::IsNullOrWhiteSpace($targetUrl)) {
    $targetUrl = 'https://a1.idc1.surf-thailand.com/test'
}

$sshUser = $env:A1_DEPLOY_SSH_USER
if ([string]::IsNullOrWhiteSpace($sshUser)) { $sshUser = 'chaba' }
$sshHost = $env:A1_DEPLOY_SSH_HOST
if ([string]::IsNullOrWhiteSpace($sshHost)) { $sshHost = 'a1.idc1.surf-thailand.com' }
$sshPort = $env:A1_DEPLOY_SSH_PORT
if ([string]::IsNullOrWhiteSpace($sshPort)) { $sshPort = '22' }
$sshKeyPath = $SshKeyPath
if ([string]::IsNullOrWhiteSpace($sshKeyPath)) {
    $sshKeyPath = $env:A1_DEPLOY_SSH_KEY_PATH
}
if ([string]::IsNullOrWhiteSpace($sshKeyPath)) {
    $sshKeyPath = Join-Path $repoRoot '.secrets\dev-host\.ssh\chaba_ed25519'
}
$isWslKey = $sshKeyPath.StartsWith('/')

if ($isWslKey) {
    $exists = $false
    try {
        $probe = Invoke-WslBash -Script "if [ -f $(ConvertTo-ShellLiteral $sshKeyPath) ]; then echo 'exists'; fi"
        $exists = $probe.Trim() -eq 'exists'
    } catch {
        $exists = $false
    }
    if (-not $exists) {
        throw "SSH key not found at $sshKeyPath inside WSL (set A1_DEPLOY_SSH_KEY_PATH)."
    }
} else {
    if (-not (Test-Path $sshKeyPath)) {
        throw "SSH key not found at $sshKeyPath (set A1_DEPLOY_SSH_KEY_PATH)."
    }
}

$env:A1_DEPLOY_SSH_KEY_PATH = $sshKeyPath
$preparedKey = Prepare-WslKeyPath -KeyPath $sshKeyPath -IsAlreadyWsl:$isWslKey
$sshKeyPathWsl = $preparedKey.Path
$sshKeyCleanupCmd = $preparedKey.Cleanup

$sshArgs = @(
    '-i', "`"$sshKeyPath`"",
    '-p', $sshPort,
    '-o', 'StrictHostKeyChecking=no',
    '-o', 'UserKnownHostsFile=/dev/null'
)
try {
    if (-not $SkipValidate) {
        Invoke-Step 'Validate Caddy config' {
            & "$scriptsRoot/validate-caddy.ps1"
        }
    }

    if (-not $SkipDeploy) {
        $deployCmd = @("cd '$wslRepoPath'", $deployScript)
        $deployEnv = @{
            SSH_KEY_PATH = $sshKeyPathWsl
            A1_DEPLOY_SSH_KEY_PATH = $sshKeyPathWsl
        }
        Invoke-WslScript "Deploy a1-idc1 assets ($Project)" $deployCmd $deployEnv
    }

    if (-not $SkipReload) {
        $reloadCmd = "ssh -i $(ConvertTo-ShellLiteral $sshKeyPathWsl) -p $sshPort -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $sshUser@$sshHost 'sudo systemctl reload caddy'"
        Invoke-Step "Reload Caddy on $sshHost (WSL)" {
            Invoke-WslBash -Script $reloadCmd | Write-Host
        }
    }

    if (-not $SkipVerify) {
        $verifyCmd = @("cd '$wslRepoPath'", "TARGET_URL='$targetUrl' $verifyScript")
        $verifyEnv = @{
            TARGET_URL = $targetUrl
            SSH_KEY_PATH = $sshKeyPathWsl
            A1_DEPLOY_SSH_KEY_PATH = $sshKeyPathWsl
        }
        Invoke-WslScript "Verify /test landing ($targetUrl)" $verifyCmd $verifyEnv
    }

    Write-Step 'Release sequence completed.'
}
finally {
    if ($sshKeyCleanupCmd) {
        Invoke-WslBash -Script $sshKeyCleanupCmd | Out-Null
    }
}
