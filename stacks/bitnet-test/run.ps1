#!/usr/bin/env pwsh
# BitNet Containerized Comparison Runner

$ErrorActionPreference = "Stop"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "BitNet CPU vs GPU Containerized Test" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# Check for Docker
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker is not installed or not in PATH"
    exit 1
}

# Check for nvidia-docker
$hasNvidia = docker info 2>&1 | Select-String "nvidia"
if (-not $hasNvidia) {
    Write-Warning "NVIDIA Docker runtime not detected. GPU tests will fail."
}

# Build image
Write-Host "`nBuilding BitNet image (this may take 10-15 minutes)..." -ForegroundColor Yellow
docker build -t bitnet:test .

# Run comparison
Write-Host "`nRunning CPU vs GPU comparison..." -ForegroundColor Green
docker run --rm --gpus all bitnet:test python compare.py 2>&1 | Tee-Object -FilePath results.log

Write-Host "`n============================================" -ForegroundColor Cyan
Write-Host "Results saved to: $PWD\results.log" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
