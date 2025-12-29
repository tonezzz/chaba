param(
  [string[]]$InventoryPaths = @(
    "docs/pc1_url.json",
    "docs/idc1_url.json",
    "docs/pc2_url.json"
  ),
  [switch]$SkipDns,
  [switch]$SkipVpnDns,
  [string]$Idc1SshHost = "103.245.164.48",
  [string]$Idc1SshUser = "chaba",
  [string]$Idc1SshKeyPath = "~/.ssh/chaba_ed25519"
)

$ErrorActionPreference = "Stop"

function Write-Step {
  param([string]$Message)
  Write-Host "[validate-url-inventory] $Message"
}

function Get-StringsRecursive {
  param([object]$Node)

  $out = New-Object System.Collections.Generic.List[string]

  if ($null -eq $Node) {
    return @()
  }

  if ($Node -is [string]) {
    return @($Node)
  }

  # ConvertFrom-Json returns PSCustomObject; traverse its properties.
  if ($Node -is [System.Management.Automation.PSObject]) {
    foreach ($p in $Node.PSObject.Properties) {
      foreach ($s in (Get-StringsRecursive -Node $p.Value)) {
        $out.Add($s)
      }
    }
    return $out.ToArray()
  }

  if ($Node -is [System.Collections.IDictionary]) {
    foreach ($k in $Node.Keys) {
      foreach ($s in (Get-StringsRecursive -Node $Node[$k])) {
        $out.Add($s)
      }
    }
    return $out.ToArray()
  }

  if ($Node -is [System.Collections.IEnumerable]) {
    foreach ($item in $Node) {
      foreach ($s in (Get-StringsRecursive -Node $item)) {
        $out.Add($s)
      }
    }
    return $out.ToArray()
  }

  return @()
}

function Get-HostFromUrl {
  param([string]$Url)

  try {
    $u = [Uri]$Url
    if ([string]::IsNullOrWhiteSpace($u.Host)) {
      return $null
    }
    return $u.Host
  } catch {
    return $null
  }
}

function Resolve-StandardDnsA {
  param([string]$Hostname)

  $records = Resolve-DnsName -Name $Hostname -Type A -DnsOnly -ErrorAction Stop
  $ips = @(
    $records |
      Where-Object { $_.Type -eq 'A' } |
      Select-Object -ExpandProperty IPAddress
  )

  return $ips
}

function Resolve-VpnDnsAThroughIdc1 {
  param([string]$Hostname)

  # Authoritative check via CoreDNS at 10.8.0.1 inside idc1 wg-easy netns.
  # Avoids misleading "Additional" output from Windows nslookup.

  $remoteScript = @'
set -euo pipefail

docker run --rm --network container:idc1-wg-easy alpine:3.20 sh -lc 'set -euo pipefail;
  apk add --no-cache bind-tools >/dev/null 2>&1;
  h="__HOST__";
  case "$h" in
    *.) hdot="$h";;
    *)  hdot="$h.";;
  esac;
  # CoreDNS may return the A record in the ADDITIONAL section (ANSWER count 0),
  # so +short would be empty. We print both ANSWER and ADDITIONAL and parse A lines.
  dig @10.8.0.1 "$hdot" A +noall +answer +additional'
'@

  $remoteScript = $remoteScript.Replace("__HOST__", $Hostname)
  $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($remoteScript -replace "`r", "")))

  $wslCmd = "set -euo pipefail; printf %s '$b64' | base64 -d | /usr/bin/ssh -i $Idc1SshKeyPath -o IdentitiesOnly=yes -o BatchMode=yes $Idc1SshUser@$Idc1SshHost 'bash -s'"
  $out = & wsl bash -lc $wslCmd 2>&1

  $ips = @(
    ($out -split "`r?`n") |
      ForEach-Object { $_.Trim() } |
      Where-Object { $_ -match '\sIN\s+A\s+\d+\.\d+\.\d+\.\d+\s*$' } |
      ForEach-Object { ($_ -split '\s+')[-1].Trim() } |
      Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' }
  )

  if (-not $ips -or $ips.Count -eq 0) {
    $preview = ($out -split "`r?`n" | Select-Object -First 12) -join "`n"
    throw ("VPN dig returned no A records for {0}. Raw output (first lines):`n{1}" -f $Hostname, $preview)
  }

  return $ips
}

$repoRoot = Split-Path -Parent $PSScriptRoot

$inventoryAbs = @()
foreach ($p in $InventoryPaths) {
  $inventoryAbs += (Resolve-Path -LiteralPath (Join-Path $repoRoot $p) -ErrorAction Stop).Path
}

Write-Step "Loading inventories"
$allUrls = New-Object System.Collections.Generic.HashSet[string]

foreach ($path in $inventoryAbs) {
  Write-Step "Reading $path"
  $json = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
  $strings = Get-StringsRecursive -Node $json
  foreach ($s in $strings) {
    if ($s -match '^(https?|udp)://') {
      [void]$allUrls.Add($s)
    }
  }
}

$hosts = New-Object System.Collections.Generic.HashSet[string]
foreach ($url in $allUrls) {
  $h = Get-HostFromUrl -Url $url
  if ($h) {
    [void]$hosts.Add($h.ToLowerInvariant())
  }
}

Write-Step ("Found {0} URLs, {1} unique hosts" -f $allUrls.Count, $hosts.Count)

if ($SkipDns) {
  Write-Step "SkipDns set; exiting."
  exit 0
}

$fail = $false
foreach ($hostname in ($hosts | Sort-Object)) {
  $isVpn = $hostname.EndsWith('.vpn')
  try {
    if ($isVpn -and -not $SkipVpnDns) {
      $ips = Resolve-VpnDnsAThroughIdc1 -Hostname $hostname
    } else {
      $ips = Resolve-StandardDnsA -Hostname $hostname
    }

    if (-not $ips -or $ips.Count -eq 0) {
      throw "No A records"
    }

    Write-Host ("[DNS] {0} -> {1}" -f $hostname, ($ips -join ','))
  } catch {
    $fail = $true
    Write-Warning ("[DNS] {0} -> FAIL ({1})" -f $hostname, $_.Exception.Message)
  }
}

if ($fail) {
  throw "One or more DNS checks failed"
}

Write-Step "OK"
