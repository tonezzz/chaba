param(
    [Parameter(Mandatory = $true)]
    [string]$Branch,

    [string]$RepoPath = 'C:\chaba',

    [string]$ComposeFile = 'stacks\pc1-stack\docker-compose.yml',

    [string]$Profile = 'mcp-suite',

    [string[]]$Services = @(),

    [switch]$NoBuild,

    [switch]$NoRestore
)

$ErrorActionPreference = 'Stop'

function Write-Step {
    param([string]$Message)
    Write-Host "[deploy-branch] $Message"
}

function Assert-RepoPath {
    if (-not (Test-Path -LiteralPath $RepoPath)) {
        throw "RepoPath not found: $RepoPath"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $RepoPath '.git'))) {
        throw "RepoPath does not look like a git repo (missing .git): $RepoPath"
    }
    if ($RepoPath -ne 'C:\chaba') {
        Write-Step "WARNING: policy is 'only deploy from C:\\chaba'. You passed RepoPath=$RepoPath"
    }
}

function Invoke-Git {
    param([string[]]$Args)
    & git -C $RepoPath @Args | Write-Host
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Args -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Get-GitOutput {
    param([string[]]$Args)
    $out = & git -C $RepoPath @Args
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Args -join ' ') failed with exit code $LASTEXITCODE"
    }
    return ($out | Out-String).Trim()
}

Assert-RepoPath

Write-Step "Fetching origin/$Branch"
Invoke-Git @('fetch', 'origin', $Branch)

$originalBranch = Get-GitOutput @('rev-parse', '--abbrev-ref', 'HEAD')
Write-Step "Current branch is '$originalBranch'"

Write-Step "Switching to '$Branch'"
Invoke-Git @('switch', $Branch)

Write-Step "Pulling latest for '$Branch'"
Invoke-Git @('pull', 'origin', $Branch)

$commitSha = Get-GitOutput @('rev-parse', 'HEAD')
$commitTitle = Get-GitOutput @('show', '-s', '--format=%s', 'HEAD')
Write-Step "Deploying $commitSha - $commitTitle"

$composePath = Join-Path $RepoPath $ComposeFile
if (-not (Test-Path -LiteralPath $composePath)) {
    throw "Compose file not found: $composePath"
}

$upArgs = @('compose', '--profile', $Profile, '-f', $composePath, 'up', '-d')
if (-not $NoBuild) {
    $upArgs += '--build'
}
if ($Services -and $Services.Count -gt 0) {
    $upArgs += $Services
}

Write-Step "Running: docker $($upArgs -join ' ')"
& docker @upArgs | Write-Host
if ($LASTEXITCODE -ne 0) {
    throw "docker compose up failed with exit code $LASTEXITCODE"
}

if (-not $NoRestore -and $originalBranch -and $originalBranch -ne $Branch) {
    Write-Step "Restoring branch '$originalBranch'"
    Invoke-Git @('switch', $originalBranch)
}

Write-Step 'Done.'
