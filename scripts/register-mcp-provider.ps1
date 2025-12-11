param(
  [Parameter(Mandatory = $true)]
  [string[]]$EnvFiles,
  [string]$ProviderName = "mcp-devops",
  [string]$BaseUrl = "http://mcp-devops:8425",
  [string]$HealthPath = "/health",
  [string]$CapabilitiesPath = "/.well-known/mcp.json"
)

$ErrorActionPreference = "Stop"

function Get-ProviderSegment {
  param(
    [string]$Name,
    [string]$Url,
    [string]$Health,
    [string]$Capabilities
  )
  $parts = @("${Name}:${Url}")
  if ($Health) {
    $parts += "health=$Health"
  }
  if ($Capabilities) {
    $parts += "capabilities=$Capabilities"
  }
  return ($parts -join "|")
}

$segment = Get-ProviderSegment -Name $ProviderName -Url $BaseUrl -Health $HealthPath -Capabilities $CapabilitiesPath

foreach ($envFile in $EnvFiles) {
  if (-not (Test-Path $envFile)) {
    throw "Env file not found: $envFile"
  }

  Write-Host "[register-mcp-provider] Updating $envFile"
  $lines = Get-Content $envFile
  $index = -1

  for ($i = 0; $i -lt $lines.Length; $i++) {
    if ($lines[$i] -match '^\s*MCP0_PROVIDERS\s*=') {
      $index = $i
      break
    }
  }

  if ($index -ge 0) {
    $existingValue = ($lines[$index] -split '=', 2)[1].Trim()
  } else {
    $existingValue = ""
  }

  $providers = @()
  if ($existingValue) {
    $providers = $existingValue -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
  }

  $alreadyPresent = $providers | Where-Object { $_ -like "${ProviderName}:*" }
  if (-not $alreadyPresent) {
    $providers += $segment
  } else {
    Write-Host "[register-mcp-provider] Provider '$ProviderName' already present in $envFile"
  }

  $newLine = "MCP0_PROVIDERS=" + ($providers -join ", ")

  if ($index -ge 0) {
    $lines[$index] = $newLine
  } else {
    $lines += $newLine
  }

  Set-Content -Path $envFile -Value $lines -NoNewline:$false
  Write-Host "[register-mcp-provider] Updated MCP0_PROVIDERS in $envFile"
}

Write-Host "[register-mcp-provider] Completed."
