#!/usr/bin/env pwsh
# Startup script for modular pc2 stacks

param(
    [string[]]$Stacks = @("core", "tools", "web", "devops"),
    [switch]$Stop,
    [switch]$Status,
    [switch]$Logs
)

$StacksDir = "stacks"

$StackCommands = @{
    "core" = @{
        "path" = "$StacksDir/pc2-core"
        "profile" = "base-tools"
        "description" = "Core services (node-runner, python-runner, redis, dev-proxy)"
    }
    "tools" = @{
        "path" = "$StacksDir/pc2-tools"
        "profile" = "mcp-suite"
        "description" = "MCP tools (mcp-docker, mcp-glama, mcp-devops)"
    }
    "web" = @{
        "path" = "$StacksDir/pc2-web"
        "profile" = ""
        "description" = "Web services (webtops-router, mcp-webtops, webtops-cp)"
    }
    "devops" = @{
        "path" = "$StacksDir/pc2-devops"
        "profile" = "mcp-suite"
        "description" = "DevOps tools (mcp-tester, mcp-agents, mcp-playwright, specialized services)"
    }
}

function Start-Stack {
    param($StackName, $Command)
    
    Write-Host "Starting $StackName..." -ForegroundColor Cyan
    $stackId = Split-Path -Leaf $Command.path
    $profile = $Command.profile
    if ($profile) {
        & (Join-Path $PSScriptRoot 'stack.ps1') -Stack $stackId -Action up -Profile $profile
    } else {
        & (Join-Path $PSScriptRoot 'stack.ps1') -Stack $stackId -Action up
    }
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
    $stackId = Split-Path -Leaf $Command.path
    & (Join-Path $PSScriptRoot 'stack.ps1') -Stack $stackId -Action down
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to stop $StackName" -ForegroundColor Red
        return $false
    }
    Write-Host "✓ $StackName stopped" -ForegroundColor Green
    return $true
}

function Get-StackStatus {
    param($StackName, $Command)
    
    $stackId = Split-Path -Leaf $Command.path
    & (Join-Path $PSScriptRoot 'stack.ps1') -Stack $stackId -Action status
    Write-Host "`n=== $StackName Status ===" -ForegroundColor Cyan
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
Write-Host "=== Starting PC2 Stacks ===" -ForegroundColor Cyan
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

Write-Host "`n✓ All PC2 stacks started successfully!" -ForegroundColor Green
Write-Host "Use './scripts/start-pc2-stacks.ps1 -Status' to check status" -ForegroundColor White
Write-Host "Use './scripts/start-pc2-stacks.ps1 -Logs' to view logs" -ForegroundColor White
