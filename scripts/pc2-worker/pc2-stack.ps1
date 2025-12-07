param(
    [ValidateSet("status", "up", "down")]
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

$composeProfile = if ([string]::IsNullOrWhiteSpace($env:PC2_COMPOSE_PROFILE)) { "mcp-suite" } else { $env:PC2_COMPOSE_PROFILE }
$dockerHost = if ([string]::IsNullOrWhiteSpace($env:PC2_DOCKER_HOST)) { "unix:///var/run/docker.sock" } else { $env:PC2_DOCKER_HOST }

function Invoke-RemoteCompose {
    param(
        [string]$RemoteCommand
    )

    $remotePath = "$remoteStacksDir/$workerDirName"
    $remoteCommand = "cd $remotePath && DOCKER_HOST=$dockerHost $RemoteCommand"
    $sshCommand = "ssh -i $sshKeyPath -p $sshPort $sshUser@$sshHost '$remoteCommand'"
    $escapedCommand = "`"$sshCommand`""
    $wslArgs = @("-u", $wslUser, "bash", "-lc", $escapedCommand)

    Write-Host "[pc2-stack] Running: wsl $($wslArgs -join ' ')"
    $process = Start-Process -FilePath "wsl" -ArgumentList $wslArgs -NoNewWindow -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "Remote command failed with exit code $($process.ExitCode)"
    }
}

switch ($Action) {
    "status" {
        Invoke-RemoteCompose -RemoteCommand "docker compose ps"
    }
    "up" {
        Invoke-RemoteCompose -RemoteCommand "docker compose --profile $composeProfile up -d"
    }
    "down" {
        Invoke-RemoteCompose -RemoteCommand "docker compose down"
    }
    default {
        throw "Unsupported action '$Action'"
    }
}
