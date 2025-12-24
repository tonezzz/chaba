param(
    [Parameter(Mandatory = $true)]
    [string]$BaseUrl,

    [string]$App = "windsurf",

    [int]$HealthTimeoutSeconds = 180,

    [string]$Username = "",
    [string]$Password = ""
)

$ErrorActionPreference = 'Stop'

function New-BasicAuthHeader {
    param(
        [string]$User,
        [string]$Pass
    )
    $bytes = [Text.Encoding]::UTF8.GetBytes("$User`:$Pass")
    $b64 = [Convert]::ToBase64String($bytes)
    return "Basic $b64"
}

function Wait-ForHealthy {
    param(
        [string]$Url,
        [int]$TimeoutSeconds,
        [hashtable]$Headers
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = $null

    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-RestMethod -Method Get -Uri $Url -Headers $Headers -TimeoutSec 10
            if ($resp -and $resp.status -eq 'healthy') {
                return $resp
            }
            $lastError = "unexpected health response"
        }
        catch {
            $lastError = $_
        }
        Start-Sleep -Seconds 3
    }

    throw "Timed out waiting for healthy at $Url. Last error: $lastError"
}

function Invoke-Mcp {
    param(
        [string]$McpUrl,
        [string]$Method,
        [hashtable]$Params,
        [hashtable]$BaseHeaders,
        [string]$SessionId = ""
    )

    $headers = @{}
    foreach ($k in $BaseHeaders.Keys) { $headers[$k] = $BaseHeaders[$k] }

    $headers['Accept'] = 'application/json, text/event-stream'
    if ($SessionId) {
        $headers['Mcp-Session-Id'] = $SessionId
    }

    $bodyObj = @{ jsonrpc = '2.0'; id = 1; method = $Method; params = $Params }
    $bodyJson = $bodyObj | ConvertTo-Json -Depth 20 -Compress

    $rh = $null
    $resp = Invoke-WebRequest -Method Post -Uri $McpUrl -ContentType 'application/json' -Headers $headers -Body $bodyJson -ResponseHeadersVariable rh

    $content = $resp.Content | ConvertFrom-Json
    return @{ Body = $content; Headers = $rh }
}

$baseHeaders = @{}
if ($Username -and $Password) {
    $baseHeaders['Authorization'] = New-BasicAuthHeader -User $Username -Pass $Password
}

$healthUrl = "$BaseUrl/health"
$mcpUrl = "$BaseUrl/mcp?app=$App"

Write-Host "[idc1-1mcp-smoke] Waiting for 1mcp healthy: $healthUrl"
Wait-ForHealthy -Url $healthUrl -TimeoutSeconds $HealthTimeoutSeconds -Headers $baseHeaders | Out-Null

Write-Host "[idc1-1mcp-smoke] MCP initialize: $mcpUrl"
$init = Invoke-Mcp -McpUrl $mcpUrl -Method 'initialize' -Params @{ protocolVersion = '2024-11-05'; clientInfo = @{ name = 'idc1-1mcp-smoke-test'; version = '1' }; capabilities = @{} } -BaseHeaders $baseHeaders

$sessionId = $init.Headers['Mcp-Session-Id']
if (-not $sessionId) {
    throw 'Missing Mcp-Session-Id header from initialize response'
}

Write-Host "[idc1-1mcp-smoke] MCP tools/list"
$tools = Invoke-Mcp -McpUrl $mcpUrl -Method 'tools/list' -Params @{} -SessionId $sessionId -BaseHeaders $baseHeaders

$toolList = $tools.Body.result.tools
if (-not $toolList) {
    throw 'tools/list returned no tools'
}

$glamaTool = $toolList | Where-Object { $_.name -match 'glama.*chat_completion|glama__chat_completion|chat_completion' } | Select-Object -First 1
if (-not $glamaTool) {
    Write-Host "[idc1-1mcp-smoke] Tools available:" 
    $toolList | ForEach-Object { Write-Host "- $($_.name)" }
    throw 'Could not find a glama chat tool in tools/list'
}

Write-Host "[idc1-1mcp-smoke] Calling tool: $($glamaTool.name)"
$call = Invoke-Mcp -McpUrl $mcpUrl -Method 'tools/call' -Params @{ name = $glamaTool.name; arguments = @{ messages = @(@{ role = 'user'; content = "Say 'pong' and nothing else." }) } } -SessionId $sessionId -BaseHeaders $baseHeaders

$callText = ($call.Body.result.content | Where-Object { $_.type -eq 'text' } | Select-Object -First 1).text
if (-not $callText) {
    throw 'tools/call returned no text content'
}

Write-Host "[idc1-1mcp-smoke] OK: $callText"
