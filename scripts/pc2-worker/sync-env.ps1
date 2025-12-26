param(
    [string]$SourcePath
)

. (Join-Path $PSScriptRoot '..\_lib\ssh.ps1')

function Get-ConfigValue {
    param(
        [string]$Value,
        [string]$Fallback
    )
    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        return $Value
    }
    return $Fallback
}

function Convert-WindowsPathToWsl {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }
    if ($Path -match '^[A-Za-z]:\\') {
        $drive = $Path.Substring(0, 1).ToLower()
        $rest = $Path.Substring(2).Replace('\', '/')
        return "/mnt/$drive/$rest"
    }
    return $Path.Replace('\', '/')
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')

$sshUser = Get-ConfigValue $env:PC2_SSH_USER 'chaba'
$sshHost = Get-ConfigValue $env:PC2_SSH_HOST 'pc2.vpn'
$sshPort = Get-ConfigValue $env:PC2_SSH_PORT '22'
$sshKeyPath = Get-ConfigValue $env:PC2_SSH_KEY_PATH (Join-Path $env:USERPROFILE '.ssh\chaba_ed25519')
$remoteStacksDir = Get-ConfigValue $env:PC2_STACKS_DIR '/home/chaba/chaba/stacks'
$workerDirName = Get-ConfigValue $env:PC2_WORKER_DIR 'pc2-worker'

$candidatePaths = @()
if ($SourcePath) { $candidatePaths += $SourcePath }
if ($env:PC2_STACK_ENV_SOURCE) { $candidatePaths += $env:PC2_STACK_ENV_SOURCE }
$candidatePaths += (Join-Path $repoRoot '.secrets\pc2\pc2-worker.env')
$candidatePaths += (Join-Path $repoRoot 'stacks\pc2-worker\.env.local')
$candidatePaths += (Join-Path $repoRoot 'stacks\pc2-worker\.env')

$resolvedSource = $null
foreach ($candidate in $candidatePaths) {
    if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path $candidate)) {
        $resolvedSource = (Resolve-Path $candidate).Path
        break
    }
}

if (-not $resolvedSource) {
    throw "Unable to find a pc2-worker .env source file. Checked: `n$($candidatePaths -join "`n")"
}

$remoteDir = "$remoteStacksDir/$workerDirName"
$remoteEnvPath = "$remoteDir/.env"
$sourcePath = $resolvedSource

Write-Host "[pc2-sync-env] Copying $resolvedSource -> ${sshUser}@${sshHost}:${remoteEnvPath}"

function Invoke-WslCommand {
    param(
        [string[]]$CommandArgs,
        [string]$Description
    )
    Write-Host "[pc2-sync-env] $Description"
    $process = Start-Process -FilePath $CommandArgs[0] -ArgumentList ($CommandArgs | Select-Object -Skip 1) -NoNewWindow -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "Command failed ($Description). Exit code: $($process.ExitCode)"
    }
}

Invoke-WslCommand -Args @(
    'powershell',
    '-NoProfile',
    '-Command',
    'Write-Host "[pc2-sync-env] Ensuring remote dir exists"'
) -Description "Ensuring $remoteDir exists on $sshHost"

Invoke-RemoteBashScript -SshUser $sshUser -SshHost $sshHost -SshPort ([int]$sshPort) -SshKeyPath $sshKeyPath -Script "mkdir -p '$remoteDir' && chmod 700 '$remoteDir'" | Out-Null

Invoke-WslCommand -Args @(
    'scp.exe',
    '-i', $sshKeyPath,
    '-o', 'IdentitiesOnly=yes',
    '-o', 'BatchMode=yes',
    '-P', $sshPort,
    $sourcePath,
    "${sshUser}@${sshHost}:${remoteEnvPath}"
) -Description "Uploading .env to $remoteEnvPath"

Write-Host "[pc2-sync-env] Secret env synced successfully."
