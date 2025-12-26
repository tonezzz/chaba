Set-StrictMode -Version Latest

function Get-DefaultSshKeyPath {
    $defaultKey = Join-Path $env:USERPROFILE '.ssh\chaba_ed25519'
    if (Test-Path $defaultKey) {
        return $defaultKey
    }
    return $defaultKey
}

function Invoke-RemoteBashScript {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$SshUser,
        [Parameter(Mandatory = $true)][string]$SshHost,
        [int]$SshPort = 22,
        [string]$SshKeyPath,
        [Parameter(Mandatory = $true)][string]$Script,
        [string[]]$ExtraSshOptions = @(),
        [switch]$AllowFailure
    )

    if ([string]::IsNullOrWhiteSpace($SshKeyPath)) {
        $SshKeyPath = Get-DefaultSshKeyPath
    }

    $payload = ($Script -replace "`r", "")
    if (-not $payload.EndsWith("`n")) {
        $payload += "`n"
    }

    $args = @(
        "-i", $SshKeyPath,
        "-o", "IdentitiesOnly=yes",
        "-o", "BatchMode=yes",
        "-p", $SshPort.ToString()
    )

    if ($ExtraSshOptions -and $ExtraSshOptions.Count) {
        foreach ($opt in $ExtraSshOptions) {
            if (-not [string]::IsNullOrWhiteSpace($opt)) {
                $args += @('-o', $opt)
            }
        }
    }

    $args += @(
        "$SshUser@$SshHost",
        "bash", "-s"
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "ssh.exe"
    $psi.Arguments = ($args -join ' ')
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi

    [void]$process.Start()

    $process.StandardInput.Write($payload)
    $process.StandardInput.Close()

    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()

    if ($stdout) { Write-Host $stdout }
    if ($stderr) { Write-Host $stderr }

    if ($process.ExitCode -ne 0 -and -not $AllowFailure) {
        throw "Remote command failed with exit code $($process.ExitCode)"
    }

    return [pscustomobject]@{
        ExitCode = $process.ExitCode
        Stdout   = $stdout
        Stderr   = $stderr
    }
}
