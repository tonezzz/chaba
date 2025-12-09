<#
.SYNOPSIS
    Gather systemd diagnostics (status, logs, configs, environment) for remote units via SSH (tunneled through WSL).
.DESCRIPTION
    This script shells into a remote Linux host via WSL + OpenSSH, captures a wide set of systemd details
    (active state, systemctl show output, journal tail, service definitions, and env files), and emits a JSON payload.
#>
[CmdletBinding()]
param(
    [string[]]$Units,
    [string]$SshUser,
    [string]$SshHost,
    [int]$SshPort,
    [string]$SshKeyPath,
    [string]$WslUser,
    [int]$TailLines = 80,
    [switch]$IncludeConfig,
    [switch]$IncludeEnv,
    [switch]$IncludeStatus
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step {
    param([string]$Message)
    Write-Host "[verify-systemd] $Message"
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')

if (-not $Units -or -not $Units.Count) {
    $Units = @('agents-api', 'glama')
}
$Units = @(
    $Units | ForEach-Object {
        if ($_ -is [string]) {
            $_.Split(',', [System.StringSplitOptions]::RemoveEmptyEntries) | ForEach-Object { $_.Trim() }
        } else {
            $_
        }
    }
) | Where-Object { $_ }
if (-not $Units.Count) {
    $Units = @('agents-api', 'glama')
}

if ([string]::IsNullOrWhiteSpace($SshUser)) { $SshUser = $env:A1_DEPLOY_SSH_USER }
if ([string]::IsNullOrWhiteSpace($SshUser)) { $SshUser = 'chaba' }

if ([string]::IsNullOrWhiteSpace($SshHost)) { $SshHost = $env:A1_DEPLOY_SSH_HOST }
if ([string]::IsNullOrWhiteSpace($SshHost)) { $SshHost = 'a1.idc1.surf-thailand.com' }

if (-not $SshPort) {
    $parsed = 0
    if ([int]::TryParse($env:A1_DEPLOY_SSH_PORT, [ref]$parsed)) {
        $SshPort = $parsed
    } else {
        $SshPort = 22
    }
}

if ([string]::IsNullOrWhiteSpace($SshKeyPath)) { $SshKeyPath = $env:A1_DEPLOY_SSH_KEY_PATH }
if ([string]::IsNullOrWhiteSpace($SshKeyPath)) {
    $SshKeyPath = Join-Path $repoRoot '.secrets\dev-host\.ssh\chaba_ed25519'
}
if (-not (Test-Path $SshKeyPath)) {
    throw "SSH key not found at $SshKeyPath (set A1_DEPLOY_SSH_KEY_PATH or pass -SshKeyPath)."
}

if ([string]::IsNullOrWhiteSpace($WslUser)) { $WslUser = $env:MCP_DEVOPS_WSL_USER }
if ([string]::IsNullOrWhiteSpace($WslUser)) { $WslUser = 'tonezzz' }

if ($TailLines -lt 0) {
    throw "-TailLines must be zero or positive."
}
if (-not $PSBoundParameters.ContainsKey('IncludeConfig')) { $IncludeConfig = $true }
if (-not $PSBoundParameters.ContainsKey('IncludeEnv')) { $IncludeEnv = $true }
if (-not $PSBoundParameters.ContainsKey('IncludeStatus')) { $IncludeStatus = $true }

function ConvertTo-WslPath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "Cannot convert blank path to WSL."
    }
    if ($Path -match '^/') {
        return $Path
    }
    $raw = & wsl.exe wslpath -a -- "`"$Path`"" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) {
        throw "Failed to convert '$Path' to WSL path."
    }
    return $raw.Trim()
}

function ConvertTo-ShellLiteral {
    param([string]$Value)
    if ($null -eq $Value) {
        return "''"
    }
    $escaped = $Value -replace "'", "'""'""'"
    return "'$escaped'"
}

function Invoke-WslBash {
    param([string]$Script)
    if ([string]::IsNullOrWhiteSpace($Script)) {
        return ""
    }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Script)
    $base64 = [Convert]::ToBase64String($bytes)
    $escaped = $base64 -replace "'", "'""'""'"
    $bashPayload = "base64 -d <<< '$escaped' | bash"
    $wslArgs = @()
    if ($WslUser) {
        $wslArgs += @('-u', $WslUser)
    }
    $wslArgs += @('bash', '-lc', $bashPayload)
    $result = & wsl.exe @wslArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        $joined = ($result -join "`n")
        throw "WSL command failed: $joined"
    }
    return $result
}

function Get-WslKeyPath {
    param([string]$Path)
    $wslPath = ConvertTo-WslPath $Path
    $literal = ConvertTo-ShellLiteral $wslPath
    if ($wslPath -notlike '/mnt/*') {
        $chmodScript = @'
chmod 600 {0} 2>/dev/null || true
'@ -f $literal
        try {
            Invoke-WslBash $chmodScript | Out-Null
        } catch {
            Write-Warning ("Failed to chmod SSH key {0}: {1}" -f $wslPath, $_.Exception.Message)
        }
        return [pscustomobject]@{
            Path    = $wslPath
            Cleanup = $null
        }
    }

    $tempPath = "/tmp/verify-systemd-key-$([Guid]::NewGuid().ToString('N'))"
    $tmpLiteral = ConvertTo-ShellLiteral $tempPath
    $script = @'
set -euo pipefail
orig={0}
tmp={1}
cp "$orig" "$tmp"
chmod 600 "$tmp"
printf '%s\n' "$tmp"
'@ -f $literal, $tmpLiteral
    $result = Invoke-WslBash $script
    $prepared = ($result -join "`n").Trim().Split("`n")[-1].Trim()
    if ([string]::IsNullOrWhiteSpace($prepared)) {
        throw "Failed to prepare SSH key copy inside WSL."
    }
    return [pscustomobject]@{
        Path    = $prepared
        Cleanup = ("rm -f {0}" -f $tmpLiteral)
    }
}

function Join-ProcessArguments {
    param([string[]]$Items)

    $type = [System.Management.Automation.LanguagePrimitives]
    $method = $type.GetMethods() |
        Where-Object { $_.Name -eq 'EscapeProcessArguments' -and $_.GetParameters().Count -eq 1 } |
        Select-Object -First 1

    if ($method) {
        return $type::EscapeProcessArguments($Items)
    }

    $needsQuotePattern = '[^\w\-\.:\/@]'
    return ($Items | ForEach-Object {
        $arg = $_
        if ([string]::IsNullOrEmpty($arg)) {
            '""'
        } elseif ($arg -notmatch $needsQuotePattern) {
            $arg
        } else {
            '"' + ($arg -replace '"', '\"') + '"'
        }
    }) -join ' '
}

$preparedKey = Get-WslKeyPath -Path $SshKeyPath
$wslKeyPath = $preparedKey.Path
$wslKeyCleanup = $preparedKey.Cleanup

function Invoke-RemoteCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [switch]$AllowFailure
    )

    $scriptLines = @(
        'set -uo pipefail',
        'export SYSTEMD_COLORS=0',
        "export SYSTEMD_PAGER=''",
        $Command
    )
    $remoteScript = ($scriptLines -join "`n")
    if (-not $remoteScript.EndsWith("`n")) {
        $remoteScript += "`n"
    }

    $sshArgs = @(
        'ssh',
        '-i', $wslKeyPath,
        '-p', $SshPort.ToString(),
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'UserKnownHostsFile=/dev/null',
        '-o', 'GlobalKnownHostsFile=/dev/null',
        '-o', 'LogLevel=ERROR',
        '-o', 'BatchMode=yes',
        '-T',
        "$SshUser@$SshHost",
        'bash',
        '-s'
    )
    $sshCommand = Join-ProcessArguments $sshArgs
    $payloadLabel = '__VERIFY_SYSTEMD_REMOTE__'
    $wslCommand = "cat <<'$payloadLabel' | $sshCommand`n$remoteScript$payloadLabel"

    $wslArgs = @()
    if ($WslUser) {
        $wslArgs += @('-u', $WslUser)
    }
    $wslArgs += @('bash', '-lc', $wslCommand)

    $output = & wsl.exe @wslArgs 2>&1
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0 -and -not $AllowFailure) {
        $joined = ($output -join "`n")
        throw "Remote command failed ($exitCode): $Command`n$joined"
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output   = ($output -join "`n")
    }
}

function ConvertFrom-SystemctlShow {
    param([string]$Text)
    $map = [ordered]@{}
    foreach ($line in ($Text -split "`r?`n")) {
        if (-not $line) { continue }
        $pair = $line.Split('=', 2)
        $key = $pair[0]
        $value = if ($pair.Count -gt 1) { $pair[1] } else { '' }
        if ($key) {
            $map[$key] = $value
        }
    }
    return $map
}

function Get-ListEntries {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return @()
    }
    return $Value -split '\s+' | Where-Object { $_ } | ForEach-Object {
        $raw = $_.Trim('"')
        $optional = $false
        if ($raw.StartsWith('-')) {
            $optional = $true
            $raw = $raw.Substring(1)
        }
        [pscustomobject]@{
            Path     = $raw
            Optional = $optional
        }
    }
}

function Get-EnvironmentEntries {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return @()
    }
    return $Value -split '\s+' | Where-Object { $_ } | ForEach-Object {
        $entry = $_.Trim()
        if (-not $entry) { return }
        $kv = $entry.Split('=', 2)
        [pscustomobject]@{
            Name  = $kv[0]
            Value = if ($kv.Count -gt 1) { $kv[1] } else { '' }
        }
    }
}

function Get-RemoteFileContent {
    param(
        [string]$Path,
        [switch]$AllowMissing
    )
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }
    $literal = ConvertTo-ShellLiteral $Path
    $cmd = @"
if [ -f $literal ]; then
  cat $literal
else
  exit 44
fi
"@
    return Invoke-RemoteCommand -Command $cmd -AllowFailure:($AllowMissing.IsPresent)
}

$propertiesToFetch = @(
    'ActiveState',
    'SubState',
    'Result',
    'ExecMainPID',
    'MainPID',
    'ExecStart',
    'ExecStartPre',
    'ExecStartPost',
    'ExecStop',
    'FragmentPath',
    'UnitFileState',
    'Environment',
    'EnvironmentFile',
    'EnvironmentFiles',
    'WorkingDirectory',
    'LoadState',
    'StateChangeTimestamp',
    'DropInPaths'
) -join ','

$unitReports = @()
foreach ($unit in $Units) {
    Write-Step "Gathering diagnostics for $unit"
    $report = [ordered]@{
        unit = $unit
    }

    $activeResult = Invoke-RemoteCommand -Command "systemctl is-active $unit" -AllowFailure
    $report.active_state = $activeResult.Output.Trim()
    if ($activeResult.ExitCode -ne 0) {
        $report.active_state_exit = $activeResult.ExitCode
    }

    $showResult = Invoke-RemoteCommand -Command "systemctl show $unit -p $propertiesToFetch" -AllowFailure
    if ($showResult.ExitCode -eq 0) {
        $report.properties = ConvertFrom-SystemctlShow $showResult.Output
    } else {
        $report.properties_error = $showResult.Output.Trim()
    }

    if ($IncludeStatus) {
        $statusResult = Invoke-RemoteCommand -Command "SYSTEMD_LOG_COLOR=0 systemctl status $unit --no-pager --plain" -AllowFailure
        $report.status = $statusResult.Output
        $report.status_exit = $statusResult.ExitCode
    }

    if ($TailLines -gt 0) {
        $logsResult = Invoke-RemoteCommand -Command "journalctl -u $unit -n $TailLines --no-pager --output short-full" -AllowFailure
        $report.logs = $logsResult.Output
        $report.logs_exit = $logsResult.ExitCode
    }

    if ($IncludeConfig) {
        $catResult = Invoke-RemoteCommand -Command "systemctl cat $unit" -AllowFailure
        $report.service_definition = $catResult.Output
        $report.service_definition_exit = $catResult.ExitCode
    }

    if ($IncludeEnv) {
        $envEntries = @()
        $envFilesMeta = @()
        if ($report.properties -and $report.properties.Environment) {
            $envEntries = Get-EnvironmentEntries $report.properties.Environment
        }
        $report.environment = $envEntries

        $envFileTokens = @()
        if ($report.properties) {
            $envFileTokens += Get-ListEntries $report.properties.EnvironmentFile
            $envFileTokens += Get-ListEntries $report.properties.EnvironmentFiles
        }
        if ($envFileTokens.Count) {
            foreach ($token in $envFileTokens) {
                $fileResult = Get-RemoteFileContent -Path $token.Path -AllowMissing
                $envFilesMeta += [ordered]@{
                    path     = $token.Path
                    optional = $token.Optional
                    present  = (($null -ne $fileResult) -and $fileResult.ExitCode -eq 0)
                    content  = if (($null -ne $fileResult) -and $fileResult.ExitCode -eq 0) { $fileResult.Output } else { $null }
                    error    = if (($null -ne $fileResult) -and $fileResult.ExitCode -ne 0) { $fileResult.Output.Trim() } else { $null }
                    exitCode = if ($fileResult) { $fileResult.ExitCode } else { $null }
                }
            }
        }
        $report.environment_files = $envFilesMeta
    }

    $unitReports += $report
}

$payload = [ordered]@{
    host        = $SshHost
    gathered_at = (Get-Date).ToString('o')
    tail_lines  = $TailLines
    include     = [ordered]@{
        status = [bool]$IncludeStatus
        logs   = ($TailLines -gt 0)
        config = [bool]$IncludeConfig
        env    = [bool]$IncludeEnv
    }
    units       = $unitReports
}

$payload | ConvertTo-Json -Depth 8

if ($wslKeyCleanup) {
    try {
        Invoke-WslBash $wslKeyCleanup | Out-Null
    } catch {
        Write-Warning "Failed to clean up temporary SSH key: $($_.Exception.Message)"
    }
}
