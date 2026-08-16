<?php
declare(strict_types=1);

$upstream = 'https://tony-dell.taila0626a.ts.net/mcp-savings.json';
$timeout = 5;
$fallback = __DIR__ . '/../apps/docs/mcp_debug/data/mcp-savings.json';

$query = $_SERVER['QUERY_STRING'] ?? '';
$upstreamUrl = $query ? "$upstream?$query" : $upstream;

$ctx = stream_context_create([
    'http' => [
        'timeout' => $timeout,
        'ignore_errors' => true,
    ],
]);

$body = @file_get_contents($upstreamUrl, false, $ctx);
$status = $http_response_header[0] ?? 'HTTP/1.0 0';

if ($body !== false && strpos($status, '200') !== false) {
    header('Content-Type: application/json');
    header('Cache-Control: public, max-age=60');
    header('Access-Control-Allow-Origin: *');
    echo $body;
    exit;
}

$fallbackBody = @file_get_contents($fallback);
if ($fallbackBody !== false) {
    header('Content-Type: application/json');
    header('Cache-Control: public, max-age=60');
    header('Access-Control-Allow-Origin: *');
    header('X-Fallback: data/mcp-savings.json');
    echo $fallbackBody;
    exit;
}

http_response_code(500);
header('Content-Type: application/json');
echo json_encode(['ok' => false, 'error' => 'live and fallback data unavailable']);
