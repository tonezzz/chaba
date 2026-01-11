#!/usr/bin/env pwsh
# Host-agnostic stack reorganization script
# Usage: ./scripts/reorganize-stacks.ps1 -HostName idc1|pc1|pc2

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("idc1", "pc1", "pc2")]
    [string]$HostName,
    
    [switch]$DryRun,
    [switch]$Force,
    [switch]$CreateTemplates,
    [string]$BackupDir = "./backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
)

Write-Host "=== Stack Reorganization for $HostName ===" -ForegroundColor Cyan

# Host-specific configurations
$HostConfigs = @{
    "idc1" = @{
        "Stacks" = @("core", "ai", "db", "web", "devops", "line")
        "CoreDir" = "stacks/idc1-stack"
        "PortRange" = "84xx"
        "Services" = @{
            "core" = @("1mcp-agent", "mcp-agents", "mcp-glama")
            "ai" = @("ollama")
            "db" = @("qdrant", "mcp-rag", "mcp-memory")
            "web" = @("webtops-router", "mcp-webtops", "webtops-cp")
            "devops" = @("mcp-devops", "mcp-tester", "mcp-playwright")
            "line" = @("mcp-line")
        }
    }
    "pc1" = @{
        "Stacks" = @("core", "auth", "web", "devops")
        "CoreDir" = "stacks/pc1-stack"
        "PortRange" = "80xx/82xx"
        "Services" = @{
            "core" = @("1mcp-agent", "mcp-agents", "mcp-rag", "mcp-tester", "mcp-playwright")
            "auth" = @("authentik-server", "authentik-worker")
            "web" = @("mcp-webtops")
            "devops" = @("mcp-devops", "mcp-quickchart")
        }
    }
    "pc2" = @{
        "Stacks" = @("core", "tools", "web", "devops")
        "CoreDir" = "stacks/pc2-worker"
        "PortRange" = "72xx/80xx"
        "Services" = @{
            "core" = @("node-runner", "python-runner", "redis", "dev-proxy")
            "tools" = @("mcp-docker", "mcp-glama", "mcp-devops")
            "web" = @("webtops-router", "mcp-webtops", "webtops-cp")
            "devops" = @("mcp-tester", "mcp-agents", "mcp-playwright")
        }
    }
}

$Config = $HostConfigs[$HostName]
if (-not $Config) {
    Write-Host "Unknown host: $HostName" -ForegroundColor Red
    exit 1
}

function New-StackFromTemplate {
    param(
        [string]$StackName,
        [string]$HostName,
        [array]$Services
    )
    
    $StackDir = "stacks/$HostName-$StackName"
    
    if ($DryRun) {
        Write-Host "DRY RUN: Would create $StackDir" -ForegroundColor Yellow
        return
    }
    
    # Create directory
    New-Item -ItemType Directory -Path $StackDir -Force | Out-Null
    
    # Generate docker-compose.yml from template
    $ComposeContent = Get-Content "templates/stack-template.yml" -Raw
    $ComposeContent = $ComposeContent -replace '\{\{STACK_NAME\}\}', $StackName
    $ComposeContent = $ComposeContent -replace '\{\{HOST\}\}', $HostName
    
    Set-Content "$StackDir/docker-compose.yml" $ComposeContent
    
    # Generate .env.example from template
    $EnvContent = Get-Content "templates/env-template.example" -Raw
    Set-Content "$StackDir/.env.example" $EnvContent
    
    # Generate README from template
    $ReadmeContent = Get-Content "templates/README-template.md" -Raw
    $ReadmeContent = $ReadmeContent -replace '\{\{STACK_NAME\}\}', $StackName
    $ReadmeContent = $ReadmeContent -replace '\{\{HOST\}\}', $HostName
    $ReadmeContent = $ReadmeContent -replace '\{\{STACK_DESCRIPTION\}\}', "$HostName $StackName services"
    
    Set-Content "$StackDir/README.md" $ReadmeContent
    
    Write-Host "Created $StackDir" -ForegroundColor Green
}

function New-NetworkConfig {
    param([string]$HostName)
    
    $NetworkFile = "stacks/$HostName-stack/create-networks.yml"
    $Networks = @()
    
    foreach ($Stack in $Config.Stacks) {
        $Networks += "  $HostName-$Stack-net:`n    driver: bridge`n    name: $HostName-$Stack-net"
    }
    
    $Content = @"
# Docker network creation for $HostName stacks
# Run once to create shared networks: docker-compose -f create-networks.yml up -d
version: "3.9"

networks:
$($Networks -join "`n")
"@
    
    if (-not $DryRun) {
        Set-Content $NetworkFile $Content
        Write-Host "Created $NetworkFile" -ForegroundColor Green
    }
}

function New-HostScripts {
    param([string]$HostName)
    
    # Generate host-specific startup script
    $StartupScript = @"
#!/usr/bin/env pwsh
# Startup script for $HostName modular stacks

param(
    [string[]]`$Stacks = @(`$($Config.Stacks -join ', '))
)

`$StacksDir = "stacks"
`$HostStackDir = "`$StacksDir/$HostName-stack"

`$StackCommands = @{
"@

    foreach ($Stack in $Config.Stacks) {
        $StartupScript += @"
    "$Stack" = @{
        "path" = "`$StacksDir/$HostName-$Stack"
        "compose" = "docker-compose"
        "description" = "$HostName $Stack services"
    }
"@
    }
    
    $StartupScript += @"

# Add startup logic here (reuse from start-idc1-stacks.ps1)
"@
    
    if (-not $DryRun) {
        Set-Content "scripts/start-$HostName-stacks.ps1" $StartupScript
        Write-Host "Created scripts/start-$HostName-stacks.ps1" -ForegroundColor Green
    }
}

# Main execution
if ($CreateTemplates) {
    Write-Host "Creating template files..." -ForegroundColor White
    # Templates already created above
    exit 0
}

if (-not $Force) {
    Write-Host "This will reorganize $Host stacks." -ForegroundColor Yellow
    Write-Host "Backup directory: $BackupDir" -ForegroundColor Yellow
    Write-Host "Run with -Force to proceed, or -DryRun to preview." -ForegroundColor Yellow
    exit 0
}

# Create backup
if (-not $DryRun) {
    Write-Host "Creating backup..." -ForegroundColor Green
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

# Generate stack directories
foreach ($Stack in $Config.Stacks) {
    New-StackFromTemplate -StackName $Stack -HostName $HostName -Services $Config.Services[$Stack]
}

# Create network configuration
New-NetworkConfig -HostName $HostName

# Create host-specific scripts
New-HostScripts -HostName $HostName

Write-Host "`n$HostName reorganization prepared!" -ForegroundColor Green
Write-Host "Review generated files and customize service configurations." -ForegroundColor White
