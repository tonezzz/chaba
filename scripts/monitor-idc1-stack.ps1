#!/usr/bin/env pwsh
# Monitor idc1 stack services

param(
    [string]$Host = "idc1.surf-thailand.com",
    [string[]]$Services = @("mcp-line", "caddy", "mcp-docker")
)

$ErrorActionPreference = "Stop"

Write-Host "📊 Monitoring idc1 stack services on $Host" -ForegroundColor Cyan

function Test-ServiceHealth {
    param(
        [string]$ServiceName,
        [string]$Url,
        [int]$TimeoutMs = 5000
    )
    
    try {
        $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
        $response = Invoke-WebRequest -Uri $Url -Method GET -TimeoutSec $TimeoutMs -ErrorAction Stop
        $stopwatch.Stop()
        
        return @{
            Name = $ServiceName
            Status = "Healthy"
            StatusCode = $response.StatusCode
            ResponseTime = $stopwatch.ElapsedMilliseconds
            Url = $Url
        }
    } catch {
        return @{
            Name = $ServiceName
            Status = "Unhealthy"
            StatusCode = if ($_.Exception.Response) { $_.Exception.Response.StatusCode } else { 0 }
            ResponseTime = $null
            Url = $Url
            Error = $_.Exception.Message
        }
    }
}

# Test each service
$results = @()

foreach ($service in $Services) {
    switch ($service) {
        "mcp-line" {
            $results += Test-ServiceHealth -ServiceName "mcp-line" -Url "https://$Host/health"
        }
        "caddy" {
            $results += Test-ServiceHealth -ServiceName "caddy" -Url "https://$Host:80/health"
        }
        "mcp-docker" {
            $results += Test-ServiceHealth -ServiceName "mcp-docker" -Url "http://$Host:8340/health"
        }
        default {
            Write-Host "⚠️ Unknown service: $service" -ForegroundColor Yellow
        }
    }
}

# Display results
Write-Host "`n📋 Service Health Report:" -ForegroundColor Yellow
Write-Host ("-" * 80) -ForegroundColor Gray

foreach ($result in $results) {
    $statusColor = if ($result.Status -eq "Healthy") { "Green" } else { "Red" }
    $statusIcon = if ($result.Status -eq "Healthy") { "✅" } else { "❌" }
    
    Write-Host "$($statusIcon) $($result.Name)" -ForegroundColor $statusColor
    Write-Host "   URL: $($result.Url)" -ForegroundColor Gray
    Write-Host "   Status: $($result.Status)" -ForegroundColor Gray
    Write-Host "   Code: $($result.StatusCode)" -ForegroundColor Gray
    
    if ($result.ResponseTime) {
        Write-Host "   Response Time: $($result.ResponseTime)ms" -ForegroundColor Gray
    }
    
    if ($result.Error) {
        Write-Host "   Error: $($result.Error)" -ForegroundColor Red
    }
    
    Write-Host ""
}

# Summary
$healthyCount = ($results | Where-Object { $_.Status -eq "Healthy" }).Count
$totalCount = $results.Count

Write-Host "📈 Summary: $healthyCount/$totalCount services healthy" -ForegroundColor $(if ($healthyCount -eq $totalCount) { "Green" } else { "Yellow" })

if ($healthyCount -lt $totalCount) {
    Write-Host "⚠️ Some services are unhealthy. Check logs and restart if needed." -ForegroundColor Yellow
    exit 1
} else {
    Write-Host "🎉 All services are healthy!" -ForegroundColor Green
}
