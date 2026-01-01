param(
    [string]$BaseUrl = "http://127.0.0.1:3051",
    [string]$App = "windsurf",
    [int]$HealthTimeoutSeconds = 120
)

$ErrorActionPreference = 'Stop'

function Wait-ForReady {
    param(
        [string]$Url,
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = $null

    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-RestMethod -Method Get -Uri $Url -TimeoutSec 10
            if ($resp -and $resp.status -eq 'ready') {
                return $resp
            }
            $lastError = "unexpected health response"
        }
        catch {
            $lastError = $_
        }
        Start-Sleep -Seconds 3
    }

    throw "Timed out waiting for ready at $Url. Last error: $lastError"
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
        $headers['mcp-session-id'] = $SessionId
        $headers['Mcp-Session-Id'] = $SessionId
    }

    $bodyObj = @{ jsonrpc = '2.0'; id = 1; method = $Method; params = $Params }
    $bodyJson = $bodyObj | ConvertTo-Json -Depth 20 -Compress

    $resp = Invoke-WebRequest -UseBasicParsing -Method Post -Uri $McpUrl -ContentType 'application/json' -Headers $headers -Body $bodyJson

    $parsed = Parse-McpResponse -Raw $resp.Content
    return @{ Body = $parsed; Headers = $resp.Headers }
}

$readyUrl = "$BaseUrl/health/ready"
$mcpUrl = "$BaseUrl/mcp?app=$App"

Write-Host "[pc1-smoke-test] Waiting for 1mcp ready: $readyUrl"
Wait-ForReady -Url $readyUrl -TimeoutSeconds $HealthTimeoutSeconds | Out-Null

Write-Host "[pc1-smoke-test] MCP initialize: $mcpUrl"
$init = Invoke-Mcp -McpUrl $mcpUrl -Method 'initialize' -Params @{ protocolVersion = '2024-11-05'; clientInfo = @{ name = 'pc1-smoke-test'; version = '1' }; capabilities = @{} }

$sessionId = $init.Headers['mcp-session-id']
if (-not $sessionId) {
    $sessionId = $init.Headers['Mcp-Session-Id']
}
if (-not $sessionId) {
    throw 'Missing mcp-session-id header from initialize response'
}

Write-Host "[pc1-smoke-test] MCP notifications/initialized"
Invoke-Mcp -McpUrl $mcpUrl -Method 'notifications/initialized' -Params @{} -SessionId $sessionId | Out-Null

Write-Host "[pc1-smoke-test] MCP tools/list"
$tools = Invoke-Mcp -McpUrl $mcpUrl -Method 'tools/list' -Params @{} -SessionId $sessionId

$toolList = $tools.Body.result.tools
if (-not $toolList) {
    throw 'tools/list returned no tools'
}

$devopsList = $toolList | Where-Object { $_.name -eq 'mcp-devops_1mcp_list_workflows' } | Select-Object -First 1
$devopsRun = $toolList | Where-Object { $_.name -eq 'mcp-devops_1mcp_run_workflow' } | Select-Object -First 1

if (-not $devopsList -or -not $devopsRun) {
    $names = ($toolList | Select-Object -ExpandProperty name) -join ', '
    throw "Could not find mcp-devops tools in tools/list. Tools: $names"
}

Write-Host "[pc1-smoke-test] Calling mcp-devops list_workflows"
$list = Invoke-Mcp -McpUrl $mcpUrl -Method 'tools/call' -Params @{ name = 'mcp-devops_1mcp_list_workflows'; arguments = @{} } -SessionId $sessionId

$listText = ($list.Body.result.content | Where-Object { $_.type -eq 'text' } | Select-Object -First 1).text
if (-not $listText) {
    throw 'mcp-devops list_workflows returned no text content'
}

$workflowsPayload = $listText | ConvertFrom-Json
if (-not $workflowsPayload.workflows -or $workflowsPayload.workflows.Count -lt 1) {
    throw 'mcp-devops list_workflows returned no workflows'
}

Write-Host "[pc1-smoke-test] Running safe devops workflow (dry-run): pc1-self-status"
$run = Invoke-Mcp -McpUrl $mcpUrl -Method 'tools/call' -Params @{ name = 'mcp-devops_1mcp_run_workflow'; arguments = @{ workflow_id = 'pc1-self-status'; dry_run = $true } } -SessionId $sessionId

$runText = ($run.Body.result.content | Where-Object { $_.type -eq 'text' } | Select-Object -First 1).text
if (-not $runText) {
    throw 'mcp-devops run_workflow returned no text content'
}

$runPayload = $runText | ConvertFrom-Json
if (-not $runPayload.command) {
    throw 'Expected dry-run command but got none'
}

Write-Host "[pc1-smoke-test] OK: workflows=$($workflowsPayload.workflows.Count) dryRunCommand=$($runPayload.command)"
