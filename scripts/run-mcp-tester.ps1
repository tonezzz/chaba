param(
    [string]$TesterBaseUrl = "http://127.0.0.1:8330",
    [string[]]$Tests,
    [switch]$FailFast,
    [int]$TimeoutSeconds = 90
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[mcp-tester] $Message"
}

function Invoke-TestRun {
    param(
        [string]$BaseUrl,
        [hashtable]$Body,
        [int]$TimeoutSeconds
    )

    $jsonBody = $Body | ConvertTo-Json -Depth 5
    Write-Step ("POST {0}/tests/run" -f $BaseUrl)
    return Invoke-RestMethod `
        -Method Post `
        -Uri ("{0}/tests/run" -f $BaseUrl.TrimEnd('/')) `
        -Body $jsonBody `
        -ContentType "application/json" `
        -TimeoutSec $TimeoutSeconds
}

if ([string]::IsNullOrWhiteSpace($TesterBaseUrl)) {
    throw "Tester base URL cannot be empty"
}

$body = @{
    fail_fast = [bool]$FailFast
}
if ($Tests -and $Tests.Count -gt 0) {
    $body.tests = $Tests
}

try {
    $response = Invoke-TestRun -BaseUrl $TesterBaseUrl -Body $body -TimeoutSeconds $TimeoutSeconds
} catch {
    Write-Error ("Failed to reach mcp-tester at {0}: {1}" -f $TesterBaseUrl, $_.Exception.Message)
    exit 1
}

if (-not $response) {
    Write-Error "No response payload received from mcp-tester"
    exit 1
}

$runId = $response.run_id
$total = $response.total
$passed = $response.passed
$failed = $response.failed
Write-Step ("Run {0}: total={1} passed={2} failed={3} duration={4}ms" -f $runId, $total, $passed, $failed, $response.duration_ms)

foreach ($result in ($response.results | Sort-Object name)) {
    $symbol = if ($result.status -eq "passed") { "✅" } elseif ($result.status -eq "skipped") { "⚪" } else { "❌" }
    $detail = if ($result.error) { $result.error } else { "status {0}" -f $result.actual_status }
    Write-Step ("{0} {1} ({2}) -> {3}" -f $symbol, $result.name, $result.method, $detail)
}

if ($failed -gt 0) {
    exit 2
}
else {
    exit 0
}
