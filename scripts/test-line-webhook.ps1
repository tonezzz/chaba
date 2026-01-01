#!/usr/bin/env pwsh
# Test LINE webhook service locally

param(
    [string]$BaseUrl = "http://127.0.0.1:8088",
    [string]$Secret = "43af9b639dbe4693cd04faef7a62229e"
)

$ErrorActionPreference = "Stop"

Write-Host "🧪 Testing LINE webhook service at $BaseUrl" -ForegroundColor Cyan

# Test 1: Health check
Write-Host "`n1. Testing health endpoint..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$BaseUrl/health" -Method GET
    Write-Host "✅ Health check passed" -ForegroundColor Green
    Write-Host "   Status: $($response.status)" -ForegroundColor Gray
    Write-Host "   Signature configured: $($response.signatureConfigured)" -ForegroundColor Gray
    Write-Host "   Access token configured: $($response.accessTokenConfigured)" -ForegroundColor Gray
} catch {
    Write-Host "❌ Health check failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Test 2: Webhook without signature (should fail)
Write-Host "`n2. Testing webhook without signature..." -ForegroundColor Yellow
try {
    $body = @{ events = @() } | ConvertTo-Json -Compress
    $response = Invoke-RestMethod -Uri "$BaseUrl/webhook/line" -Method POST -Body $body -ContentType "application/json" -ErrorAction Stop
    Write-Host "❌ Expected 401 error, got success" -ForegroundColor Red
} catch {
    if ($_.Exception.Response.StatusCode -eq 401) {
        Write-Host "✅ Correctly rejected request without signature" -ForegroundColor Green
    } else {
        Write-Host "❌ Unexpected error: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

# Test 3: Webhook with valid signature
Write-Host "`n3. Testing webhook with valid signature..." -ForegroundColor Yellow
try {
    $payload = @{
        events = @(
            @{
                type = "message"
                message = @{
                    type = "text"
                    text = "Hello test"
                }
                source = @{
                    type = "user"
                    userId = "test-user-id"
                }
                replyToken = "test-reply-token"
            }
        )
    }
    
    $body = $payload | ConvertTo-Json -Compress
    
    # Generate LINE signature
    $hmac = [System.Security.Cryptography.HMACSHA256]::new([System.Text.Encoding]::UTF8.GetBytes($Secret))
    $signatureBytes = $hmac.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($body))
    $signature = [System.Convert]::ToBase64String($signatureBytes)
    
    $headers = @{
        "Content-Type" = "application/json"
        "X-Line-Signature" = $signature
    }
    
    $response = Invoke-RestMethod -Uri "$BaseUrl/webhook/line" -Method POST -Body $body -Headers $headers -ErrorAction Stop
    Write-Host "✅ Webhook processed successfully" -ForegroundColor Green
    Write-Host "   Events processed: $($response.events)" -ForegroundColor Gray
    Write-Host "   Status: $($response.status)" -ForegroundColor Gray
} catch {
    Write-Host "❌ Webhook test failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "`n🎉 All tests passed!" -ForegroundColor Green
