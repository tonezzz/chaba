#!/usr/bin/env pwsh
# Startup script for modular pc1 stacks

param(
    [string[]]$Stacks = @("ingress", "mcp", "services", "db", "gpu", "devops", "auth"),
    [switch]$Stop,
    [switch]$Status,
    [switch]$Logs
)

$StacksDir = "stacks"
$ScriptDir = Split-Path -Parent $PSCommandPath
$StackScript = Join-Path $ScriptDir 'stack.ps1'

$StackCommands = @{
    "ingress" = @{
        "stack" = "pc1-web"
        "profile" = ""
        "description" = "Ingress + web UI (Caddy on :80/:443, mcp-webtops)"
    }
    "mcp" = @{
        "stack" = "pc1-stack"
        "profile" = "mcp-suite"
        "description" = "1MCP hub (3051/3052) + core MCP servers that still live in pc1-stack"
    }
    "services" = @{
        "stack" = "pc1-services"
        "profile" = ""
        "description" = "Shared app services (mcp-glama, mcp-github-models, mcp-openai-gateway, ollama, etc.)"
    }
    "db" = @{
        "stack" = "pc1-db"
        "profile" = ""
        "description" = "Database + storage (qdrant, mcp-rag, mcp-doc-archiver, minio, vault, etc.)"
    }
    "gpu" = @{
        "stack" = "pc1-gpu"
        "profile" = ""
        "description" = "GPU services (mcp-cuda, mcp-imagen-light, mcp-rag-light)"
    }
    "devops" = @{
        "stack" = "pc1-devops"
        "profile" = ""
        "description" = "DevOps MCP tools (mcp-devops, mcp-quickchart)"
    }
    "auth" = @{
        "stack" = "pc1-auth"
        "profile" = ""
        "description" = "Authentication (authentik server/worker)"
    }
}

function Start-Stack {
    param($StackName, $Command)
    
    Write-Host "Starting $StackName..." -ForegroundColor Cyan
    & pwsh $StackScript -Stack $Command.stack -Action up -Profile $Command.profile
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
    & pwsh $StackScript -Stack $Command.stack -Action down
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to stop $StackName" -ForegroundColor Red
        return $false
    }
    Write-Host "✓ $StackName stopped" -ForegroundColor Green
    return $true
}

function Get-StackStatus {
    param($StackName, $Command)
    
    Write-Host "`n=== $StackName Status ===" -ForegroundColor Cyan
    & pwsh $StackScript -Stack $Command.stack -Action status -Profile $Command.profile
}

function Get-StackLogs {
    param($StackName, $Command)
    
    Write-Host "`n=== $StackName Logs ===" -ForegroundColor Cyan
    & pwsh $StackScript -Stack $Command.stack -Action logs -Profile $Command.profile
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
