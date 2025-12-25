param(
  [string]$Endpoint = "https://1mcp.idc1.surf-thailand.com/mcp?app=windsurf",
  [string[]]$ComposePathCandidates = @(
    "/opt/chaba/stacks/idc1-stack/docker-compose.yml",
    "/root/chaba/stacks/idc1-stack/docker-compose.yml"
  ),
  [string]$ProjectName = "idc1-stack"
)

$ErrorActionPreference = "Stop"

$cred = Get-Credential -Message "Basic auth for 1mcp.idc1"
$pair = "{0}:{1}" -f $cred.UserName, ($cred.GetNetworkCredential().Password)
$basic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair))
$headers = @{ Authorization = "Basic $basic" }

function Invoke-JsonRpc {
  param(
    [string]$Url,
    [hashtable]$Body
  )
  return Invoke-RestMethod -Method Post -Uri $Url -Headers $headers -ContentType "application/json" -Body ($Body | ConvertTo-Json -Depth 20)
}

Write-Host "[idc1] checking /health on $Endpoint"
$health = Invoke-RestMethod -Uri ($Endpoint -replace "/mcp\?app=.*$","/health") -Method Get -Headers $headers
$health | ConvertTo-Json -Depth 6 | Write-Host

Write-Host "[idc1] creating SSE session"
$sse = Invoke-RestMethod -Uri ($Endpoint -replace "/mcp\?app=.*$","/mcp/sse") -Method Post -Headers $headers
$sessionId = $sse.session_id
if (-not $sessionId) { throw "No session_id returned" }

$rpcUrl = ($Endpoint -replace "/mcp\?app=.*$","/mcp/messages") + "?session_id=$sessionId"

foreach ($composePath in $ComposePathCandidates) {
  try {
    Write-Host "[idc1] attempting compose up with path: $composePath"
    $resp = Invoke-JsonRpc -Url $rpcUrl -Body @{
      jsonrpc = "2.0";
      id = 1;
      method = "tools/invoke";
      params = @{ name = "docker_1mcp_compose-control"; arguments = @{ command = "up"; compose_path = $composePath; project_name = $ProjectName } }
    }
    $resp | ConvertTo-Json -Depth 8 | Write-Host
    Write-Host "[idc1] deploy completed"
    break
  } catch {
    Write-Host "[idc1] failed for $composePath: $($_.Exception.Message)"
  }
}
