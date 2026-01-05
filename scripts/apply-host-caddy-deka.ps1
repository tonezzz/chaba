param(
  [string]$CaddyExe = "C:\\caddy\\caddy.exe",
  [string]$Caddyfile = "C:\\caddy\\Caddyfile",
  [string]$Domain = "deka.pc1.vpn",
  [string]$Backend = "127.0.0.1:3170"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (!(Test-Path -LiteralPath $CaddyExe)) {
  throw "Caddy exe not found at '$CaddyExe'"
}
if (!(Test-Path -LiteralPath $Caddyfile)) {
  throw "Caddyfile not found at '$Caddyfile'"
}

$backup = "$Caddyfile.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Copy-Item -LiteralPath $Caddyfile -Destination $backup -Force

$siteBlock = @"

# deka chat
$Domain {
  tls internal

  route {
    handle_path /chat* {
      reverse_proxy $Backend
    }

    handle /_next/* {
      reverse_proxy $Backend
    }

    handle /api/* {
      reverse_proxy $Backend
    }

    handle /favicon.ico {
      reverse_proxy $Backend
    }

    handle {
      redir /chat/ 302
    }
  }
}
"@

$text = Get-Content -LiteralPath $Caddyfile -Raw

# Replace existing block if present; otherwise append.
$pattern = '(?s)# deka chat\s*' + [regex]::Escape($Domain) + '\s*\{.*?\n\}'
if ($text -match $pattern) {
  $text = [regex]::Replace($text, $pattern, ($siteBlock.TrimEnd() + "`n"))
} else {
  $text = $text.TrimEnd() + $siteBlock + "`n"
}

Set-Content -LiteralPath $Caddyfile -Value $text -Encoding ascii

& $CaddyExe validate --config $Caddyfile --adapter caddyfile | Out-Host
& $CaddyExe reload --config $Caddyfile --adapter caddyfile | Out-Host

Write-Host "Applied $Domain -> $Backend (backup: $backup)"
