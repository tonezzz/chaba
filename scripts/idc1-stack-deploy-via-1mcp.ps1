param(
  [string]$Endpoint = "https://1mcp.idc1.surf-thailand.com/mcp?app=windsurf",
  [string[]]$ComposePathCandidates = @(
    "/home/chaba/chaba/stacks/idc1-stack/docker-compose.yml",
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

$baseUrl = ($Endpoint -replace "/mcp\?app=.*$", "")

function Invoke-JsonRpc {
  param(
    [string]$Url,
    [hashtable]$Body
  )

  $accepts = @(
    "application/json",
    "application/json, text/event-stream"
  )

  $json = ($Body | ConvertTo-Json -Depth 20)
  foreach ($accept in $accepts) {
    try {
      $h = @{} + $headers
      $h["Accept"] = $accept
      return Invoke-RestMethod -Method Post -Uri $Url -Headers $h -ContentType "application/json" -Body $json
    } catch {
      # If gateway rejects Accept, it returns 406. Try next Accept.
      if ($_.Exception.Message -match "406") {
        continue
      }
      throw
    }
  }

  throw "MCP endpoint rejected all Accept headers we tried"
}

Write-Host "[idc1] checking /health on $Endpoint"
$health = Invoke-RestMethod -Uri "$baseUrl/health" -Method Get -Headers $headers
$health | ConvertTo-Json -Depth 6 | Write-Host

Write-Host "[idc1] using direct MCP JSON-RPC at $Endpoint"
$rpcUrl = $Endpoint

# Optional: verify tool exists (best-effort)
try {
  $list = Invoke-JsonRpc -Url $rpcUrl -Body @{ jsonrpc = "2.0"; id = 1; method = "tools/list"; params = @{} }
  $names = @($list.result.tools | ForEach-Object { $_.name })
  if ($names -notcontains "docker_1mcp_compose-control") {
    Write-Host "[idc1] warning: docker_1mcp_compose-control not found in tools/list"
  }
} catch {
  Write-Host "[idc1] warning: tools/list failed: $($_.Exception.Message)"
}

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
    Write-Host "[idc1] failed for ${composePath}: $($_.Exception.Message)"
  }
}
