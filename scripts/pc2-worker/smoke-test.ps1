param(
    [string]$BaseUrl = "http://1mcp.pc2.vpn:3050",
    [string]$App = "windsurf",
    [int]$HealthTimeoutSeconds = 120
)

$ErrorActionPreference = 'Stop'

function Wait-ForHealthy {
    param(
        [string]$Url,
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = $null

    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-RestMethod -Method Get -Uri $Url -TimeoutSec 10
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

function Parse-McpResponse {
    param(
        [string]$Raw
    )

    if (-not $Raw) {
        throw 'Empty MCP response'
    }

    $trim = $Raw.Trim()

    # Some 1mcp responses come back as SSE frames:
    # event: message\n
    # data: {...json...}\n\n
    if ($trim.StartsWith('event:')) {
        $m = [regex]::Matches($Raw, '(?m)^data:\s*(\{.*\})\s*$')
        if (-not $m -or $m.Count -eq 0) {
            throw "Unable to locate SSE data payload in response: $Raw"
        }
        return ($m[$m.Count - 1].Groups[1].Value | ConvertFrom-Json)
    }

    return ($Raw | ConvertFrom-Json)
}

function Invoke-Mcp {
    param(
        [string]$McpUrl,
        [string]$Method,
        [hashtable]$Params,
        [string]$SessionId = ""
    )

    $headers = @{ Accept = 'application/json, text/event-stream' }
    if ($SessionId) {
        $headers['Mcp-Session-Id'] = $SessionId
    }

    $bodyObj = @{ jsonrpc = '2.0'; id = 1; method = $Method; params = $Params }
    $bodyJson = $bodyObj | ConvertTo-Json -Depth 20 -Compress

    $resp = Invoke-WebRequest -UseBasicParsing -Method Post -Uri $McpUrl -ContentType 'application/json' -Headers $headers -Body $bodyJson

    $content = Parse-McpResponse -Raw $resp.Content
    return @{ Body = $content; Headers = $resp.Headers }
}

$healthUrl = "$BaseUrl/health"
$mcpUrl = "$BaseUrl/mcp?app=$App"

Write-Host "[smoke-test] Waiting for 1mcp healthy: $healthUrl"
Wait-ForHealthy -Url $healthUrl -TimeoutSeconds $HealthTimeoutSeconds | Out-Null

Write-Host "[smoke-test] MCP initialize: $mcpUrl"
$init = Invoke-Mcp -McpUrl $mcpUrl -Method 'initialize' -Params @{ protocolVersion = '2024-11-05'; clientInfo = @{ name = 'pc2-smoke-test'; version = '1' }; capabilities = @{} }

$sessionId = $init.Headers['Mcp-Session-Id']
if (-not $sessionId) {
    throw 'Missing Mcp-Session-Id header from initialize response'
}

Write-Host "[smoke-test] MCP tools/list"
$tools = Invoke-Mcp -McpUrl $mcpUrl -Method 'tools/list' -Params @{} -SessionId $sessionId

$toolList = $tools.Body.result.tools
if (-not $toolList) {
    throw 'tools/list returned no tools'
}

$glamaTool = $toolList | Where-Object { $_.name -match 'glama.*chat_completion|glama__chat_completion|chat_completion' } | Select-Object -First 1
if (-not $glamaTool) {
    throw 'Could not find a glama chat tool in tools/list'
}

Write-Host "[smoke-test] Calling tool: $($glamaTool.name)"
$call = Invoke-Mcp -McpUrl $mcpUrl -Method 'tools/call' -Params @{ name = $glamaTool.name; arguments = @{ messages = @(@{ role = 'user'; content = "Say 'pong' and nothing else." }) } } -SessionId $sessionId

$callText = ($call.Body.result.content | Where-Object { $_.type -eq 'text' } | Select-Object -First 1).text
if (-not $callText) {
    throw 'tools/call returned no text content'
}

Write-Host "[smoke-test] OK: $callText"
