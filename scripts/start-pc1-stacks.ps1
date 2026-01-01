#!/usr/bin/env pwsh
# Startup script for modular pc1 stacks

param(
    [string[]]$Stacks = @("core", "auth", "web", "devops"),
    [switch]$Stop,
    [switch]$Status,
    [switch]$Logs
)

$StacksDir = "stacks"
$Pc1StackDir = "$StacksDir/pc1-stack"

$StackCommands = @{
    "core" = @{
        "path" = $Pc1StackDir
        "compose" = "docker-compose --profile mcp-suite"
        "description" = "Core MCP services (1mcp-agent, mcp-agents, mcp-rag, mcp-tester, mcp-playwright)"
    }
    "auth" = @{
        "path" = "$StacksDir/pc1-auth"
        "compose" = "docker-compose --profile authentik"
        "description" = "Authentication services (authentik-server, authentik-worker)"
    }
    "web" = @{
        "path" = "$StacksDir/pc1-web"
        "compose" = "docker-compose"
        "description" = "Web services (webtop2, mcp-webtop)"
    }
    "devops" = @{
        "path" = "$StacksDir/pc1-devops"
        "compose" = "docker-compose"
        "description" = "DevOps tools (mcp-devops, mcp-quickchart)"
    }
}

function Start-Stack {
    param($StackName, $Command)
    
    Write-Host "Starting $StackName..." -ForegroundColor Cyan
    Set-Location $Command.path
    docker-compose --profile mcp-suite up -d
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to start $StackName" -ForegroundColor Red
        return $false
    }
    Write-Host "✓ $StackName started" -ForegroundColor Green
    return $true
}

function Stop-Stack {
    param($StackName, $Command)
    
    Write-Host "Stopping $StackName..." -ForegroundColor Yellow
    Set-Location $Command.path
    docker-compose down
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to stop $StackName" -ForegroundColor Red
        return $false
    }
    Write-Host "✓ $StackName stopped" -ForegroundColor Green
    return $true
}

function Get-StackStatus {
    param($StackName, $Command)
    
    Set-Location $Command.path
    $status = docker-compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
    Write-Host "`n=== $StackName Status ===" -ForegroundColor Cyan
    Write-Host $status
}

function Get-StackLogs {
    param($StackName, $Command)
    
    Set-Location $Command.path
    Write-Host "`n=== $StackName Logs ===" -ForegroundColor Cyan
    docker-compose logs -f --tail=50
}

# Main execution
if ($Stop) {
    foreach ($stack in $Stacks) {
        if ($StackCommands.ContainsKey($stack)) {
            Stop-Stack -StackName $stack -Command $StackCommands[$stack]
        } else {
            Write-Host "Unknown stack: $stack" -ForegroundColor Red
        }
    }
    exit 0
}

if ($Status) {
    foreach ($stack in $Stacks) {
        if ($StackCommands.ContainsKey($stack)) {
            Get-StackStatus -StackName $stack -Command $StackCommands[$stack]
        } else {
            Write-Host "Unknown stack: $stack" -ForegroundColor Red
        }
    }
    exit 0
}

if ($Logs) {
    foreach ($stack in $Stacks) {
        if ($StackCommands.ContainsKey($stack)) {
            Get-StackLogs -StackName $stack -Command $StackCommands[$stack]
        } else {
            Write-Host "Unknown stack: $stack" -ForegroundColor Red
        }
    }
    exit 0
}

# Start stacks
Write-Host "=== Starting PC1 Stacks ===" -ForegroundColor Cyan
Write-Host "Stacks: $($Stacks -join ', ')" -ForegroundColor White

foreach ($stack in $Stacks) {
    if ($StackCommands.ContainsKey($stack)) {
        $success = Start-Stack -StackName $stack -Command $StackCommands[$stack]
        if (-not $success) {
            Write-Host "Failed to start $stack. Exiting." -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "Unknown stack: $stack" -ForegroundColor Red
        exit 1
    }
}

Write-Host "`n✓ All PC1 stacks started successfully!" -ForegroundColor Green
Write-Host "Use './scripts/start-pc1-stacks.ps1 -Status' to check status" -ForegroundColor White
Write-Host "Use './scripts/start-pc1-stacks.ps1 -Logs' to view logs" -ForegroundColor White
