param(
    [string]$Branch = $env:MCP_DEVOPS_GIT_BRANCH,
    [switch]$SkipValidate,
    [switch]$SkipDeploy,
    [switch]$SkipReload,
    [switch]$SkipVerify,
    [switch]$DryRun,
    [switch]$NoRestore,
    [string]$SshKeyPath
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($Branch)) {
    $Branch = 'main'
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$releaseScript = Join-Path $PSScriptRoot 'release-a1-idc1.ps1'
$gitExe = (Get-Command git -ErrorAction Stop).Source

function Write-Step {
    param([string]$Message)
    Write-Host "[dever-deploy-git-branch] $Message"
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

function Invoke-GitStep {
    param(
        [string]$Description,
        [string[]]$Arguments
    )

    Invoke-Step $Description {
        $gitArgs = @('-C', $repoRoot) + $Arguments
        & $gitExe @gitArgs | Write-Host
    }
}

function Get-GitOutput {
    param([string[]]$Arguments)

    $gitArgs = @('-C', $repoRoot) + $Arguments
    $result = & $gitExe @gitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
    if ($null -eq $result) {
        return ''
    }
    return ($result | Out-String).Trim()
}

Write-Step "Preparing git branch '$Branch'"
$originalBranch = Get-GitOutput @('rev-parse', '--abbrev-ref', 'HEAD')

Invoke-GitStep "Fetch origin/$Branch" @('fetch', 'origin', $Branch)
Invoke-GitStep "Checkout $Branch" @('checkout', $Branch)
Invoke-GitStep "Pull latest for $Branch" @('pull', 'origin', $Branch)

$commitSha = Get-GitOutput @('rev-parse', 'HEAD')
$commitTitle = Get-GitOutput @('show', '-s', '--format=%s', 'HEAD')
Write-Step "Resolved commit $commitSha - $commitTitle"

$releaseArgs = @('-Project', "git-branch:$Branch")
if ($SkipValidate) { $releaseArgs += '-SkipValidate' }
if ($SkipDeploy) { $releaseArgs += '-SkipDeploy' }
if ($SkipReload) { $releaseArgs += '-SkipReload' }
if ($SkipVerify) { $releaseArgs += '-SkipVerify' }
if ($DryRun) { $releaseArgs += '-DryRun' }
if (-not [string]::IsNullOrWhiteSpace($SshKeyPath)) {
    $releaseArgs += @('-SshKeyPath', $SshKeyPath)
}

Write-Step "Running release pipeline for $Branch"
& $releaseScript @releaseArgs

if ($LASTEXITCODE -ne 0) {
    throw "release-a1-idc1.ps1 failed with exit code $LASTEXITCODE"
}

if (-not $NoRestore -and -not [string]::IsNullOrWhiteSpace($originalBranch) -and $originalBranch -ne $Branch) {
    Invoke-GitStep "Restore branch '$originalBranch'" @('checkout', $originalBranch)
}

Write-Step 'Deployment flow completed.'
