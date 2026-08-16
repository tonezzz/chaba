<?php
/**
 * Same-origin proxy for the tony-omen mcp-debug CORS endpoint.
 * chaba.h3 is served over HTTPS; this PHP endpoint fetches the HTTP backend
 * so the browser never makes a mixed-content request.
 */
$host = getenv('MCP_DEBUG_HOST') ?: '100.68.142.13';
$port = getenv('MCP_DEBUG_PORT') ?: '9100';
$upstream = "http://{$host}:{$port}/mcp-savings.json";

$ch = curl_init($upstream);
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT => 5,
    CURLOPT_CONNECTTIMEOUT => 2,
    CURLOPT_FOLLOWLOCATION => false,
]);

$response = curl_exec($ch);
$err = curl_error($ch);
$httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);

header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');

if ($response === false) {
    http_response_code(503);
    echo json_encode(['ok' => false, 'error' => 'proxy upstream unavailable', 'details' => $err]);
    exit;
}

http_response_code($httpCode ?: 200);
echo $response;
