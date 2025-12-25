param(
  [string]$Endpoint = "http://1mcp.pc2.vpn:3050",
  [string]$ComposePath = "/opt/chaba/stacks/pc2-worker/docker-compose.yml",
  [string]$ProjectName = "pc2-worker"
)

$ErrorActionPreference = "Stop"

function Invoke-JsonRpc {
  param(
    [string]$Url,
    [hashtable]$Body,
    [hashtable]$Headers = @{}
  )
  return Invoke-RestMethod -Method Post -Uri $Url -Headers $Headers -ContentType "application/json" -Body ($Body | ConvertTo-Json -Depth 20)
}

Write-Host "[pc2-worker] checking /health on $Endpoint"
$health = Invoke-RestMethod -Uri "$Endpoint/health" -Method Get
$health | ConvertTo-Json -Depth 6 | Write-Host

Write-Host "[pc2-worker] creating SSE session"
$sse = Invoke-RestMethod -Uri "$Endpoint/mcp/sse" -Method Post
$sessionId = $sse.session_id
if (-not $sessionId) { throw "No session_id returned" }

$rpcUrl = "$Endpoint/mcp/messages?session_id=$sessionId"

Write-Host "[pc2-worker] bringing stack up via docker_1mcp_compose-control"
$resp = Invoke-JsonRpc -Url $rpcUrl -Body @{
  jsonrpc = "2.0";
  id = 1;
  method = "tools/invoke";
  params = @{ name = "docker_1mcp_compose-control"; arguments = @{ command = "up"; compose_path = $ComposePath; project_name = $ProjectName } }
}
$resp | ConvertTo-Json -Depth 8 | Write-Host

Write-Host "[pc2-worker] done" 
