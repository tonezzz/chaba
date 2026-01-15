param(
    [ValidateSet("status", "up", "down", "sync")]
    [string]$Action = "status"
)

$sshUser = $env:PC2_SSH_USER
if ([string]::IsNullOrWhiteSpace($sshUser)) {
    $sshUser = "chaba"
}

$sshHost = $env:PC2_SSH_HOST
if ([string]::IsNullOrWhiteSpace($sshHost)) {
    $sshHost = "pc2"
}

$sshPort = $env:PC2_SSH_PORT
if ([string]::IsNullOrWhiteSpace($sshPort)) {
    $sshPort = "22"
}

$sshKeyPath = $env:PC2_SSH_KEY_PATH
if ([string]::IsNullOrWhiteSpace($sshKeyPath)) {
    $sshKeyPath = "/home/tonezzz/.ssh/chaba_ed25519"
}

$wslUser = $env:PC2_WSL_USER
if ([string]::IsNullOrWhiteSpace($wslUser)) {
    $wslUser = "tonezzz"
}

$remoteStacksDir = $env:PC2_STACKS_DIR
if ([string]::IsNullOrWhiteSpace($remoteStacksDir)) {
    $remoteStacksDir = "/home/chaba/chaba/stacks"
}

$workerDirName = $env:PC2_WORKER_DIR
if ([string]::IsNullOrWhiteSpace($workerDirName)) {
    $workerDirName = "pc2-worker"
}

$repoRoot = $env:PC2_REPO_ROOT
if ([string]::IsNullOrWhiteSpace($repoRoot)) {
    $repoRoot = "/home/chaba/chaba"
}

$gitRemote = if ([string]::IsNullOrWhiteSpace($env:PC2_GIT_REMOTE)) { "https://github.com/tonezzz/chaba.git" } else { $env:PC2_GIT_REMOTE }
$gitRef = if ([string]::IsNullOrWhiteSpace($env:PC2_GIT_REF)) { "main" } else { $env:PC2_GIT_REF }
$composeProfile = if ([string]::IsNullOrWhiteSpace($env:PC2_COMPOSE_PROFILE)) { "mcp-suite" } else { $env:PC2_COMPOSE_PROFILE }
$dockerHost = if ([string]::IsNullOrWhiteSpace($env:PC2_DOCKER_HOST)) { "unix:///var/run/docker.sock" } else { $env:PC2_DOCKER_HOST }
$syncBeforeUp = $env:PC2_SYNC_BEFORE_UP
if ([string]::IsNullOrWhiteSpace($syncBeforeUp)) {
    $syncBeforeUp = "true"
}
$shouldSyncBeforeUp = $syncBeforeUp.Trim().ToLower() -ne "false"

function Escape-DoubleQuote {
    param(
        [string]$Value
    )
    if ($null -eq $Value) {
        return ""
    }
    return $Value -replace '"', '\"'
}

function Invoke-RemoteCommand {
    param(
        [string]$RemoteCommand
    )

    $sshCommand = "ssh -i $sshKeyPath -p $sshPort $sshUser@$sshHost '$RemoteCommand'"
    $escapedCommand = "`"$sshCommand`""
    $wslArgs = @("-u", $wslUser, "bash", "-lc", $escapedCommand)

    Write-Host "[pc2-stack] Running: wsl $($wslArgs -join ' ')"
    $process = Start-Process -FilePath "wsl" -ArgumentList $wslArgs -NoNewWindow -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "Remote command failed with exit code $($process.ExitCode)"
    }
}

function Invoke-RemoteCompose {
    param(
        [string]$RemoteCommand
    )

    $remotePath = "$remoteStacksDir/$workerDirName"
    $compositeCommand = "cd $remotePath && DOCKER_HOST=$dockerHost $RemoteCommand"
    Invoke-RemoteCommand -RemoteCommand $compositeCommand
}

function Sync-RemoteRepo {
    $repoRootEsc = Escape-DoubleQuote -Value $repoRoot
    $gitRemoteEsc = Escape-DoubleQuote -Value $gitRemote
    $gitRefEsc = Escape-DoubleQuote -Value $gitRef

    $remoteCommand = @'
set -euo pipefail
mkdir -p "{0}"
cd "{0}"
if [ ! -d .git ]; then
  git init
  git remote add origin "{1}"
fi
git remote set-url origin "{1}"
git fetch origin --prune
if git show-ref --verify --quiet "refs/heads/{2}"; then
  git checkout "{2}"
else
  git checkout -B "{2}" "origin/{2}"
fi
git reset --hard "origin/{2}"
git submodule update --init --recursive || true
'@ -f $repoRootEsc, $gitRemoteEsc, $gitRefEsc

    Invoke-RemoteCommand -RemoteCommand $remoteCommand
}

switch ($Action) {
    "status" {
        Invoke-RemoteCompose -RemoteCommand "docker compose ps"
    }
    "up" {
        if ($shouldSyncBeforeUp) {
            Sync-RemoteRepo
        }
        Invoke-RemoteCompose -RemoteCommand "docker compose --profile $composeProfile up -d"
    }
    "down" {
        Invoke-RemoteCompose -RemoteCommand "docker compose down"
    }
    "sync" {
        Sync-RemoteRepo
    }
    default {
        throw "Unsupported action '$Action'"
    }
}
