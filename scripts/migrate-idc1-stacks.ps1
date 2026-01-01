#!/usr/bin/env pwsh
# Migration script for idc1 stack reorganization
# Migrates from monolithic idc1-stack to modular structure

param(
    [switch]$DryRun,
    [switch]$Force,
    [string]$BackupDir = "./backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
)

Write-Host "=== IDC1 Stack Migration ===" -ForegroundColor Cyan

$StacksDir = "stacks"
$Idc1StackDir = "$StacksDir/idc1-stack"
$NewStacks = @("idc1-db", "idc1-web", "idc1-devops", "idc1-line")

# Safety checks
if (-not $Force) {
    Write-Host "This will migrate idc1-stack to modular structure." -ForegroundColor Yellow
    Write-Host "Backup directory: $BackupDir" -ForegroundColor Yellow
    Write-Host "Run with -Force to proceed, or -DryRun to preview." -ForegroundColor Yellow
    exit 0
}

# Create backup
if (-not $DryRun) {
    Write-Host "Creating backup..." -ForegroundColor Green
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    Copy-Item -Path "$Idc1StackDir/docker-compose.original.yml" -Destination "$BackupDir/" -Force
    Copy-Item -Path "$Idc1StackDir/.env.original.example" -Destination "$BackupDir/" -Force
    if (Test-Path "$Idc1StackDir/.env") {
        Copy-Item -Path "$Idc1StackDir/.env" -Destination "$BackupDir/" -Force
    }
    Write-Host "Backup created: $BackupDir" -ForegroundColor Green
}

# Create shared networks
Write-Host "Creating shared networks..." -ForegroundColor Green
if (-not $DryRun) {
    Set-Location $Idc1StackDir
    docker-compose -f create-networks.yml up -d
    Set-Location ../../
}

# Instructions for manual migration
Write-Host "`n=== Migration Instructions ===" -ForegroundColor Cyan
Write-Host "1. Stop existing idc1-stack:" -ForegroundColor White
Write-Host "   cd $Idc1StackDir && docker-compose --profile mcp-suite --profile webtops down" -ForegroundColor Gray
Write-Host ""
Write-Host "2. Create .env files for new stacks:" -ForegroundColor White
foreach ($stack in $NewStacks) {
    $envFile = "$StacksDir/$stack/.env.example"
    if (Test-Path $envFile) {
        Write-Host "   cp $envFile $StacksDir/$stack/.env" -ForegroundColor Gray
    }
}
Write-Host ""
Write-Host "3. Start new modular stacks:" -ForegroundColor White
Write-Host "   # Core services" -ForegroundColor Gray
Write-Host "   cd $Idc1StackDir && docker-compose --profile mcp-suite up -d" -ForegroundColor Gray
Write-Host "   # Database stack" -ForegroundColor Gray
Write-Host "   cd $StacksDir/idc1-db && docker-compose up -d" -ForegroundColor Gray
Write-Host "   # Web services" -ForegroundColor Gray
Write-Host "   cd $StacksDir/idc1-web && docker-compose up -d" -ForegroundColor Gray
Write-Host "   # DevOps tools" -ForegroundColor Gray
Write-Host "   cd $StacksDir/idc1-devops && docker-compose up -d" -ForegroundColor Gray
Write-Host "   # LINE service" -ForegroundColor Gray
Write-Host "   cd $StacksDir/idc1-line && docker-compose up -d" -ForegroundColor Gray
Write-Host ""
Write-Host "4. Verify migration:" -ForegroundColor White
Write-Host "   docker ps | grep idc1" -ForegroundColor Gray
Write-Host ""

if ($DryRun) {
    Write-Host "DRY RUN: No changes made. Use -Force to execute migration." -ForegroundColor Yellow
} else {
    Write-Host "Migration prepared! Follow the instructions above to complete." -ForegroundColor Green
}
