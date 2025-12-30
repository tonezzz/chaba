param(
  [string]$AppDir = "sites\a1-idc1\test\ai_app_src"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$fullDir = Join-Path $repoRoot $AppDir

if (-not (Test-Path $fullDir)) {
  throw "Missing app directory: $fullDir"
}

Write-Host "[ai-app-fast] repoRoot=$repoRoot"
Write-Host "[ai-app-fast] appDir=$fullDir"

Push-Location $fullDir
try {
  & npm ci
  if ($LASTEXITCODE -ne 0) { throw "npm ci failed ($LASTEXITCODE)" }

  & npm run lint
  if ($LASTEXITCODE -ne 0) { throw "npm run lint failed ($LASTEXITCODE)" }

  & npm run typecheck
  if ($LASTEXITCODE -ne 0) { throw "npm run typecheck failed ($LASTEXITCODE)" }

  & npm run build
  if ($LASTEXITCODE -ne 0) { throw "npm run build failed ($LASTEXITCODE)" }

  & npm run publish:test
  if ($LASTEXITCODE -ne 0) { throw "npm run publish:test failed ($LASTEXITCODE)" }

  Write-Host "[ai-app-fast] ok"
} finally {
  Pop-Location
}
