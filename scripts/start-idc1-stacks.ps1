#!/usr/bin/env pwsh
# Startup script for modular idc1 stacks

param(
    [string[]]$Stacks = @("core", "ai", "db", "web", "devops", "line"),
    [switch]$Stop,
    [switch]$Status,
    [switch]$Logs
)

$StacksDir = "stacks"
$Idc1StackDir = "$StacksDir/idc1-stack"

$StackCommands = @{
    "core" = @{
        "path" = $Idc1StackDir
        "compose" = "docker-compose --profile mcp-suite"
        "description" = "Core MCP services (1mcp-agent, mcp-agents, mcp-glama)"
    }
    "ai" = @{
        "path" = "$StacksDir/idc1-ai"
        "compose" = "docker-compose"
        "description" = "AI/ML services (ollama)"
    }
    "db" = @{
        "path" = "$StacksDir/idc1-db"
        "compose" = "docker-compose"
        "description" = "Database stack (qdrant, mcp-rag, mcp-memory)"
    }
    "web" = @{
        "path" = "$StacksDir/idc1-web"
        "compose" = "docker-compose"
        "description" = "Web services (webtops)"
    }
    "devops" = @{
        "path" = "$StacksDir/idc1-devops"
        "compose" = "docker-compose"
        "description" = "DevOps tools (mcp-devops, mcp-tester, mcp-playwright)"
    }
    "line" = @{
        "path" = "$StacksDir/idc1-line"
        "compose" = "docker-compose"
        "description" = "LINE webhook service"
    }
}

function Show-Status {
    Write-Host "=== IDC1 Stack Status ===" -ForegroundColor Cyan
    
    foreach ($stack in $StackCommands.Keys) {
        $config = $StackCommands[$stack]
        Write-Host "`n$stack ($($config.description)):" -ForegroundColor White
        
        if (Test-Path $config.path) {
            Set-Location $config.path
            $status = docker-compose ps -q
            if ($status) {
                docker-compose ps
            } else {
                Write-Host "  Not running" -ForegroundColor Gray
            }
        } else {
            Write-Host "  Stack directory not found" -ForegroundColor Red
        }
    }
    
    Set-Location ../../
}

function Show-Logs {
    param($StackFilter)
    
    foreach ($stack in $StackCommands.Keys) {
        if ($StackFilter -and $stack -notin $StackFilter) { continue }
        
        $config = $StackCommands[$stack]
        Write-Host "`n=== $stack Logs ===" -ForegroundColor Cyan
        
        if (Test-Path $config.path) {
            Set-Location $config.path
            docker-compose logs --tail=20
        }
    }
    
    Set-Location ../../
}

function Stop-Stacks {
    Write-Host "=== Stopping IDC1 Stacks ===" -ForegroundColor Yellow
    
    # Stop in reverse order
    $reverseStacks = $Stacks | Sort-Object -Descending
    foreach ($stack in $reverseStacks) {
        if (-not $StackCommands.ContainsKey($stack)) { continue }
        
        $config = $StackCommands[$stack]
        Write-Host "Stopping $stack..." -ForegroundColor White
        
        if (Test-Path $config.path) {
            Set-Location $config.path
            docker-compose down
        }
    }
    
    Set-Location ../../
    Write-Host "All stacks stopped." -ForegroundColor Green
}

function Start-Stacks {
    Write-Host "=== Starting IDC1 Stacks ===" -ForegroundColor Green
    
    # Ensure networks exist
    Write-Host "Ensuring shared networks..." -ForegroundColor White
    Set-Location $Idc1StackDir
    docker-compose -f create-networks.yml up -d
    Set-Location ../../
    
    # Start stacks in order
    foreach ($stack in $Stacks) {
        if (-not $StackCommands.ContainsKey($stack)) { 
            Write-Host "Unknown stack: $stack" -ForegroundColor Red
            continue 
        }
        
        $config = $StackCommands[$stack]
        Write-Host "Starting $stack ($($config.description))..." -ForegroundColor White
        
        if (Test-Path $config.path) {
            Set-Location $config.path
            $envFile = ".env"
            if (-not (Test-Path $envFile)) {
                Write-Host "  Warning: .env file not found, copying from .env.example" -ForegroundColor Yellow
                if (Test-Path ".env.example") {
                    Copy-Item ".env.example" ".env"
                }
            }
            
            docker-compose up -d
            Write-Host "  Started $stack" -ForegroundColor Green
        } else {
            Write-Host "  Stack directory not found: $($config.path)" -ForegroundColor Red
        }
    }
    
    Set-Location ../../
    Write-Host "`nStack startup complete!" -ForegroundColor Green
    Write-Host "Run './scripts/start-idc1-stacks.ps1 -Status' to check status." -ForegroundColor Gray
}

# Main execution
if ($Status) {
    Show-Status
} elseif ($Logs) {
    Show-Logs -StackFilter $Stacks
} elseif ($Stop) {
    Stop-Stacks
} else {
    Start-Stacks
}
