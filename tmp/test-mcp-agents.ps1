$proc = Start-Process -FilePath "node" -ArgumentList "index.js" -WorkingDirectory "c:\chaba\mcp\mcp-agents" -PassThru
Start-Sleep -Seconds 3
try {
  Invoke-WebRequest -Uri 'http://127.0.0.1:8046/.well-known/mcp.json' -UseBasicParsing | Select-Object -ExpandProperty Content
} finally {
  if ($proc -and -not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force
  }
}
