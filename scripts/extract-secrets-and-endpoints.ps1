param(
  [string]$RepoRoot = "C:\chaba",
  [string]$OutFile = "C:\chaba\.secrets\.env.all-secrets",
  [switch]$Force,
  [switch]$IncludeBlankValues,
  [switch]$OnlyUrlsReferencedByEnvKeys
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Normalize-Key([string]$s) {
  $s = $s -replace '[^A-Za-z0-9]', '_'
  $s = $s -replace '_+', '_'
  $s = $s.Trim('_')
  if ([string]::IsNullOrWhiteSpace($s)) { return $null }
  return $s.ToUpperInvariant()
}

function Is-ExcludedPath([string]$fullPath) {
  $p = $fullPath.Replace('/', '\').ToLowerInvariant()

  $excluded = @(
    "\\.git\\",
    "\\node_modules\\",
    "\\.secrets\\",
    "\\secrets\\",
    "\\data\\",
    "\\artifacts\\",
    "\\logs\\",
    "\\tmp\\",
    "\\temp\\",
    "\\.models\\",
    "\\.tools\\",
    "\\stacks\\",
    "\\installer\\.cache\\"
  )

  foreach ($e in $excluded) {
    if ($p.Contains($e)) {
      if ($e -eq "\\stacks\\") {
        if ($p.Contains("\\stacks\\") -and ($p.Contains("\\data\\") -or $p.Contains("\\logs\\"))) {
          return $true
        }
        continue
      }
      return $true
    }
  }

  return $false
}

function Get-CandidateFiles([string]$root) {
  $exts = @('.env', '.json', '.yml', '.yaml')

  Get-ChildItem -Path $root -File -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object {
      $fp = $_.FullName
      if (Is-ExcludedPath $fp) { return $false }

      $name = $_.Name.ToLowerInvariant()
      if ($name -eq '.env.example' -or $name.EndsWith('.env.example')) { return $false }
      if ($name -eq '.env.template' -or $name.EndsWith('.env.template')) { return $false }

      $ext = $_.Extension.ToLowerInvariant()
      if ($exts -contains $ext) { return $true }

      if ($name -like 'docker-compose*.yml' -or $name -like 'docker-compose*.yaml') { return $true }
      if ($name -like '1mcp*.json') { return $true }

      return $false
    }
}

function Extract-EnvPairs([string[]]$lines, [hashtable]$pairs, [string]$sourcePath, [hashtable]$keySources) {
  foreach ($line in $lines) {
    $t = $line.Trim()
    if ([string]::IsNullOrWhiteSpace($t)) { continue }
    if ($t.StartsWith('#')) { continue }

    if ($t -match '^(?<k>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?<v>.*)$') {
      $k = $Matches['k']
      $v = $Matches['v']

      $kNorm = Normalize-Key $k
      if (-not $kNorm) { continue }

      $v = $v.Trim()
      if (($v.StartsWith('"') -and $v.EndsWith('"')) -or ($v.StartsWith("'") -and $v.EndsWith("'"))) {
        if ($v.Length -ge 2) { $v = $v.Substring(1, $v.Length - 2) }
      }

      if (-not $IncludeBlankValues -and [string]::IsNullOrWhiteSpace($v)) { continue }

      $pairs[$kNorm] = $v

      if ($null -ne $keySources) {
        if (-not $keySources.ContainsKey($kNorm)) {
          $keySources[$kNorm] = New-Object System.Collections.Generic.HashSet[string]
        }
        if (-not [string]::IsNullOrWhiteSpace($sourcePath)) {
          [void]$keySources[$kNorm].Add($sourcePath)
        }
      }
    }
  }
}

function Extract-Urls([string]$text, [hashtable]$urls, [string]$sourcePath, [hashtable]$urlSources) {
  $pattern = '(?i)https?://[^\s"''\)\]>]+'
  $matches = [regex]::Matches($text, $pattern)
  foreach ($m in $matches) {
    $u = $m.Value
    if ([string]::IsNullOrWhiteSpace($u)) { continue }
    $urls[$u] = $true

    if ($null -ne $urlSources) {
      if (-not $urlSources.ContainsKey($u)) {
        $urlSources[$u] = New-Object System.Collections.Generic.HashSet[string]
      }
      if (-not [string]::IsNullOrWhiteSpace($sourcePath)) {
        [void]$urlSources[$u].Add($sourcePath)
      }
    }
  }
}

function Get-Urls([string]$text) {
  $pattern = '(?i)https?://[^\s"''\)\]>]+'
  $matches = [regex]::Matches($text, $pattern)
  $out = New-Object System.Collections.Generic.List[string]
  foreach ($m in $matches) {
    $u = $m.Value
    if ([string]::IsNullOrWhiteSpace($u)) { continue }
    $out.Add($u)
  }
  return $out
}

function Get-UrlHost([string]$url) {
  try {
    return ([uri]$url).Host
  } catch {
    return $null
  }
}

if (-not (Test-Path -LiteralPath $RepoRoot)) {
  throw "RepoRoot not found: $RepoRoot"
}

$secretsDir = Split-Path -Parent $OutFile
if (-not (Test-Path -LiteralPath $secretsDir)) {
  New-Item -ItemType Directory -Path $secretsDir -Force | Out-Null
}

if ((Test-Path -LiteralPath $OutFile) -and -not $Force) {
  throw "OutFile already exists: $OutFile (use -Force to overwrite)"
}

$pairs = @{}
$urls = @{}
$urlToKeys = @{}
$keyToUrls = @{}
$keySources = @{}
$urlSources = @{}

$files = @(Get-CandidateFiles -root $RepoRoot)
foreach ($f in $files) {
  try {
    $content = Get-Content -LiteralPath $f.FullName -ErrorAction Stop
  } catch {
    continue
  }

  Extract-EnvPairs -lines $content -pairs $pairs -sourcePath $f.FullName -keySources $keySources
  Extract-Urls -text ($content -join "`n") -urls $urls -sourcePath $f.FullName -urlSources $urlSources
}

foreach ($k in $pairs.Keys) {
  $v = $pairs[$k]
  if ($null -eq $v) { continue }

  $foundUrls = @(Get-Urls -text ([string]$v))
  if ($foundUrls.Count -gt 0) {
    if (-not $keyToUrls.ContainsKey($k)) {
      $keyToUrls[$k] = New-Object System.Collections.Generic.HashSet[string]
    }
    foreach ($u in $foundUrls) {
      [void]$keyToUrls[$k].Add($u)
    }
  }

  foreach ($u in $foundUrls) {
    if (-not $urlToKeys.ContainsKey($u)) {
      $urlToKeys[$u] = New-Object System.Collections.Generic.HashSet[string]
    }
    [void]$urlToKeys[$u].Add($k)
  }
}

if ($OnlyUrlsReferencedByEnvKeys) {
  $filteredUrls = @{}
  foreach ($u in $urlToKeys.Keys) {
    $filteredUrls[$u] = $true
  }
  $urls = $filteredUrls

  $filteredUrlSources = @{}
  foreach ($u in $urls.Keys) {
    if ($urlSources.ContainsKey($u)) {
      $filteredUrlSources[$u] = $urlSources[$u]
    }
  }
  $urlSources = $filteredUrlSources
}

$endpointPairs = @{}
$idx = 1
foreach ($u in ($urls.Keys | Sort-Object)) {
  $k = "ENDPOINT_{0:D4}" -f $idx
  $endpointPairs[$k] = $u
  $idx++
}

$stableEndpointPairs = @{}
foreach ($k in ($keyToUrls.Keys | Sort-Object)) {
  $urlList = @($keyToUrls[$k] | Sort-Object)
  if ($urlList.Count -eq 0) { continue }
  if ($urlList.Count -eq 1) {
    $stableEndpointPairs[("ENDPOINT_{0}" -f $k)] = $urlList[0]
  } else {
    $i = 1
    foreach ($u in $urlList) {
      $stableEndpointPairs[("ENDPOINT_{0}_{1:D2}" -f $k, $i)] = $u
      $i++
    }
  }
}

$urlsByHost = @{}
foreach ($u in ($urls.Keys | Sort-Object)) {
  $h = Get-UrlHost -url $u
  if ([string]::IsNullOrWhiteSpace($h)) { $h = "_invalid" }
  if (-not $urlsByHost.ContainsKey($h)) {
    $urlsByHost[$h] = New-Object System.Collections.Generic.HashSet[string]
  }
  [void]$urlsByHost[$h].Add($u)
}

$allPairs = @{}
foreach ($k in $pairs.Keys) { $allPairs[$k] = $pairs[$k] }
foreach ($k in $endpointPairs.Keys) { $allPairs[$k] = $endpointPairs[$k] }
foreach ($k in $stableEndpointPairs.Keys) { $allPairs[$k] = $stableEndpointPairs[$k] }

$header = @(
  "# Generated by scripts/extract-secrets-and-endpoints.ps1",
  ("# GeneratedAt={0:o}" -f (Get-Date)),
  ("# RepoRoot={0}" -f $RepoRoot),
  ("# FilesScanned={0}" -f $files.Count),
  ("# EnvKeys={0}" -f $pairs.Count),
  ("# Urls={0}" -f $urls.Count),
  ("# UrlsWithReferencingKeys={0}" -f $urlToKeys.Count),
  ("# KeysWithUrls={0}" -f $keyToUrls.Count),
  ("# StableEndpointKeys={0}" -f $stableEndpointPairs.Count),
  ("# KeysWithSources={0}" -f $keySources.Count),
  ("# UrlsWithSources={0}" -f $urlSources.Count),
  ("# OnlyUrlsReferencedByEnvKeys={0}" -f ([bool]$OnlyUrlsReferencedByEnvKeys)),
  ""
)

$outLines = New-Object System.Collections.Generic.List[string]
foreach ($h in $header) {
  $outLines.Add([string]$h)
}

$outLines.Add("# ---")
$outLines.Add("# URL inventory (grouped by host)")
$outLines.Add("# ---")
foreach ($urlHost in ($urlsByHost.Keys | Sort-Object)) {
  $outLines.Add(("# Host: {0} ({1})" -f $urlHost, $urlsByHost[$urlHost].Count))
  foreach ($u in ($urlsByHost[$urlHost] | Sort-Object)) {
    $outLines.Add(("#   {0}" -f $u))
  }
  $outLines.Add("#")
}

$outLines.Add("# ---")
$outLines.Add("# URL -> Env keys referencing it")
$outLines.Add("# ---")
foreach ($u in ($urlToKeys.Keys | Sort-Object)) {
  $keys = ($urlToKeys[$u] | Sort-Object)
  $outLines.Add(("# {0}" -f $u))
  $outLines.Add(("#   Keys: {0}" -f (($keys -join ', '))))
}

$outLines.Add("")
$outLines.Add("# ---")
$outLines.Add("# Env key -> URLs")
$outLines.Add("# ---")
foreach ($k in ($keyToUrls.Keys | Sort-Object)) {
  $urlList = @($keyToUrls[$k] | Sort-Object)
  if ($urlList.Count -eq 0) { continue }
  $outLines.Add(("# {0}" -f $k))
  foreach ($u in $urlList) {
    $outLines.Add(("#   {0}" -f $u))
  }
}

$outLines.Add("")
$outLines.Add("# ---")
$outLines.Add("# Env key -> sources")
$outLines.Add("# ---")
foreach ($k in ($keySources.Keys | Sort-Object)) {
  $srcList = @($keySources[$k] | Sort-Object)
  if ($srcList.Count -eq 0) { continue }
  $outLines.Add(("# {0}" -f $k))
  foreach ($s in $srcList) {
    $outLines.Add(("#   {0}" -f $s))
  }
}

$outLines.Add("")
$outLines.Add("# ---")
$outLines.Add("# URL -> sources")
$outLines.Add("# ---")
foreach ($u in ($urlSources.Keys | Sort-Object)) {
  $srcList = @($urlSources[$u] | Sort-Object)
  if ($srcList.Count -eq 0) { continue }
  $outLines.Add(("# {0}" -f $u))
  foreach ($s in $srcList) {
    $outLines.Add(("#   {0}" -f $s))
  }
}

$outLines.Add("")
$outLines.Add("# ---")
$outLines.Add("# Flattened KEY=VALUE export")
$outLines.Add("# ---")

foreach ($k in ($allPairs.Keys | Sort-Object)) {
  $v = $allPairs[$k]
  if ($null -eq $v) { $v = '' }

  $needsQuotes = ($v -match '[\s#]' )
  if ($needsQuotes) {
    $v = $v.Replace('"', '\"')
    $outLines.Add("$k=`"$v`"")
  } else {
    $outLines.Add("$k=$v")
  }
}

Set-Content -LiteralPath $OutFile -Value $outLines -Encoding UTF8

Write-Host ("Wrote: {0}" -f $OutFile)
Write-Host ("Files scanned: {0}" -f $files.Count)
Write-Host ("Env keys: {0}" -f $pairs.Count)
Write-Host ("URLs: {0}" -f $urls.Count)
