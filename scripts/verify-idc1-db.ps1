#!/usr/bin/env pwsh
# Verify idc1-db PostgreSQL connectivity from pc1

param(
    [string]$HostName = "idc1.surf-thailand.com",
    [int]$Port = 5432,
    [string]$Database = "chaba",
    [string]$Username = "chaba",
    [string]$Password = "changeme"
)

Write-Host "=== idc1-db Connectivity Verification ===" -ForegroundColor Cyan
Write-Host ""

# Test 1: Network connectivity
Write-Host "Test 1: Network connectivity to ${HostName}:${Port}" -ForegroundColor Yellow
$tcpTest = Test-NetConnection -ComputerName $HostName -Port $Port -WarningAction SilentlyContinue
if ($tcpTest.TcpTestSucceeded) {
    Write-Host "  ✅ TCP connection successful" -ForegroundColor Green
} else {
    Write-Host "  ❌ TCP connection failed" -ForegroundColor Red
    Write-Host "  Check: VPN connection to idc1" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Test 2: DNS resolution
Write-Host "Test 2: DNS resolution" -ForegroundColor Yellow
$dnsResult = Resolve-DnsName -Name $HostName -ErrorAction SilentlyContinue
if ($dnsResult) {
    $ip = $dnsResult[0].IPAddress
    Write-Host "  ✅ ${HostName} resolves to ${ip}" -ForegroundColor Green
} else {
    Write-Host "  ⚠️ DNS resolution failed (may use hosts file)" -ForegroundColor Yellow
}
Write-Host ""

# Test 3: Check WireGuard VPN
Write-Host "Test 3: WireGuard VPN status" -ForegroundColor Yellow
$wgInterface = Get-NetAdapter | Where-Object { $_.Name -like "*WireGuard*" -or $_.InterfaceDescription -like "*WireGuard*" }
if ($wgInterface) {
    Write-Host "  ✅ WireGuard adapter found: $($wgInterface.Name)" -ForegroundColor Green
    if ($wgInterface.Status -eq "Up") {
        Write-Host "  ✅ WireGuard is connected" -ForegroundColor Green
    } else {
        Write-Host "  ❌ WireGuard is not connected (Status: $($wgInterface.Status))" -ForegroundColor Red
    }
} else {
    Write-Host "  ⚠️ WireGuard adapter not found (may use different VPN)" -ForegroundColor Yellow
}
Write-Host ""

# Test 4: Docker network (if running in container context)
Write-Host "Test 4: Docker network access" -ForegroundColor Yellow
$dockerAvailable = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerAvailable) {
    $vpnNetwork = docker network ls | Select-String "idc1-stack_vpn"
    if ($vpnNetwork) {
        Write-Host "  ✅ VPN network found: $($vpnNetwork.Line)" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️ VPN network 'idc1-stack_vpn' not found" -ForegroundColor Yellow
        Write-Host "  Available networks:" -ForegroundColor Gray
        docker network ls | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
    }
} else {
    Write-Host "  ⚠️ Docker not available in this context" -ForegroundColor Yellow
}
Write-Host ""

# Test 5: PostgreSQL connection (requires psql or Python)
Write-Host "Test 5: PostgreSQL connection" -ForegroundColor Yellow

# Try Python first
$pythonTest = python3 -c "
import sys
try:
    import psycopg2
    conn = psycopg2.connect(
        host='$HostName',
        port=$Port,
        database='$Database',
        user='$Username',
        password='$Password'
    )
    cur = conn.cursor()
    cur.execute('SELECT version()')
    version = cur.fetchone()[0]
    print(f'✅ PostgreSQL connected: {version[:50]}...')
    cur.close()
    conn.close()
    sys.exit(0)
except ImportError:
    print('⚠️ psycopg2 not installed')
    sys.exit(1)
except Exception as e:
    print(f'❌ PostgreSQL connection failed: {e}')
    sys.exit(1)
" 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "  $pythonTest" -ForegroundColor Green
} else {
    Write-Host "  $pythonTest" -ForegroundColor Red
    Write-Host "  To test manually, run:" -ForegroundColor Gray
    Write-Host "  python3 -c \"import psycopg2; conn = psycopg2.connect(host='$HostName', port=$Port, database='$Database', user='$Username', password='$Password'); print('Connected')\"" -ForegroundColor Gray
}
Write-Host ""

# Summary
Write-Host "=== Summary ===" -ForegroundColor Cyan
Write-Host "Connection string: postgresql://${Username}:****@${HostName}:${Port}/${Database}" -ForegroundColor White
Write-Host ""
Write-Host "If all tests pass, your services can connect to idc1-db." -ForegroundColor Green
Write-Host "If any test fails, check VPN connection and idc1-db stack status." -ForegroundColor Yellow
