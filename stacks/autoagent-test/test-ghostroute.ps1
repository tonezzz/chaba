# GhostRoute Test Workflow for Windows
# 
# This script runs the GhostRoute discovery test on autoagent-test
# Usage: .\test-ghostroute.ps1

$ErrorActionPreference = "Stop"

Write-Host "===================================" -ForegroundColor Cyan
Write-Host "GhostRoute Full Test Workflow" -ForegroundColor Cyan
Write-Host "===================================" -ForegroundColor Cyan

# Check if running from correct directory
if (-not (Test-Path "docker-compose.yml")) {
    Write-Error "Must run from stacks/autoagent-test directory"
    exit 1
}

Write-Host ""
Write-Host "[1/5] Building autoagent-test container..." -ForegroundColor Yellow
docker-compose build --no-cache autoagent

Write-Host ""
Write-Host "[2/5] Starting container..." -ForegroundColor Yellow
docker-compose up -d autoagent

Write-Host ""
Write-Host "[3/5] Waiting for container to be ready..." -ForegroundColor Yellow
Start-Sleep -Seconds 2

Write-Host ""
Write-Host "[4/5] Running GhostRoute discovery test..." -ForegroundColor Yellow
docker exec -it autoagent-test bash -c "cd /app && python test-ghostroute.py"

Write-Host ""
Write-Host "[5/5] Verifying discovery files..." -ForegroundColor Yellow
docker exec autoagent-test ls -la /workspace/discovery/ghostroute/latest/

Write-Host ""
Write-Host "===================================" -ForegroundColor Green
Write-Host "Test Complete!" -ForegroundColor Green
Write-Host "===================================" -ForegroundColor Green
Write-Host ""
Write-Host "Discovery files available at:" -ForegroundColor White
Write-Host "  - docker: /workspace/discovery/ghostroute/latest/" -ForegroundColor Gray
Write-Host "  - host:   ./discovery/ghostroute/latest/ (via volume)" -ForegroundColor Gray
Write-Host ""
Write-Host "To query results:" -ForegroundColor White
Write-Host "  docker exec autoagent-test python /app/mcp-query.py best" -ForegroundColor Gray
Write-Host "  docker exec autoagent-test python /app/mcp-query.py fallbacks" -ForegroundColor Gray
Write-Host "  docker exec autoagent-test python /app/mcp-query.py config" -ForegroundColor Gray
Write-Host ""
