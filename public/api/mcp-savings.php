<?php
declare(strict_types=1);

$upstream = 'https://tony-dell.taila0626a.ts.net/mcp-savings.json';
$fallback = __DIR__ . '/../apps/docs/mcp_debug/data/mcp-savings.json';
$previous = __DIR__ . '/../apps/docs/mcp_debug/data/mcp-savings-previous.json';

$query = $_SERVER['QUERY_STRING'] ?? '';
$upstreamUrl = $query ? "$upstream?$query" : $upstream;
$force = isset($_GET['refresh']) && in_array($_GET['refresh'], ['1', 'true', 'yes'], true);

// For forced refresh, wait up to 15 seconds to give tony-dell a chance to respond with the
// current cache and a 202 "refreshing" marker. For normal reads, wait up to 60 seconds.
$timeout = $force ? 15 : 60;

$ctx = stream_context_create([
    'http' => [
        'timeout' => $timeout,
        'ignore_errors' => true,
    ],
]);

$body = @file_get_contents($upstreamUrl, false, $ctx);
$status = $http_response_header[0] ?? 'HTTP/1.0 0';
$statusOk = strpos($status, '200') !== false;
$statusAccepted = strpos($status, '202') !== false;
$decoded = null;
$isUpstreamOk = false;

if ($body !== false && ($statusOk || $statusAccepted)) {
    $decoded = @json_decode($body, true);
    if ($decoded !== null) {
        $isUpstreamOk = true;
    }
}

if ($isUpstreamOk) {
    // For 200 (fresh or cached data), store it as the fallback. For 202 (refresh in progress),
    // pass through immediately without overwriting the fallback.
    if ($statusOk) {
        if (file_exists($fallback)) {
            @copy($fallback, $previous);
        }
        @file_put_contents($fallback, $body);
    }
    header('Content-Type: application/json');
    header('Cache-Control: public, max-age=60');
    header('Access-Control-Allow-Origin: *');
    http_response_code($statusAccepted ? 202 : 200);
    echo json_encode($decoded);
    exit;
}

$fallbackBody = @file_get_contents($fallback);
if ($fallbackBody !== false) {
    $fallbackData = @json_decode($fallbackBody, true);
    if ($fallbackData !== null) {
        $fallbackData['ok'] = false;
        $fallbackData['error'] = 'Live data unavailable; showing cached snapshot.';
        $fallbackData['live_error'] = $status;
    }
    header('Content-Type: application/json');
    header('Cache-Control: public, max-age=60');
    header('Access-Control-Allow-Origin: *');
    header('X-Fallback: data/mcp-savings.json');
    http_response_code(200);
    echo json_encode($fallbackData);
    exit;
}

http_response_code(500);
header('Content-Type: application/json');
echo json_encode(['ok' => false, 'error' => 'live and fallback data unavailable']);