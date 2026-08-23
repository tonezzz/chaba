<?php
declare(strict_types=1);

$host = $_GET['host'] ?? '';
$command = $_GET['command'] ?? '';

if (!$host || !$command) {
    http_response_code(400);
    header('Content-Type: application/json');
    echo json_encode(['ok' => false, 'error' => 'host and command query params required']);
    exit;
}

$upstream = 'https://tony-omen.taila0626a.ts.net/mcp-table.json?' . http_build_query(['host' => $host, 'command' => $command]);
$timeout = 60;

$ctx = stream_context_create([
    'http' => [
        'timeout' => $timeout,
        'ignore_errors' => true,
    ],
]);

$body = @file_get_contents($upstream, false, $ctx);
$status = $http_response_header[0] ?? 'HTTP/1.0 0';

if ($body !== false && strpos($status, '200') !== false) {
    header('Content-Type: application/json');
    header('Cache-Control: public, max-age=60');
    header('Access-Control-Allow-Origin: *');
    echo $body;
    exit;
}

http_response_code(500);
header('Content-Type: application/json');
echo json_encode(['ok' => false, 'error' => 'live table data unavailable']);
