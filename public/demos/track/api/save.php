<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');

$body = file_get_contents('php://input');
if ($body === false || $body === '') {
    http_response_code(400);
    echo json_encode(['error' => 'empty body']);
    exit;
}

$data = json_decode($body, true);
if (!is_array($data)) {
    http_response_code(400);
    echo json_encode(['error' => 'invalid json: ' . json_last_error_msg()]);
    exit;
}

$course = $data['course'] ?? '';
if ($course === '' || !preg_match('/^[a-zA-Z0-9_-]+$/', $course)) {
    http_response_code(400);
    echo json_encode(['error' => 'missing or invalid course']);
    exit;
}

$overrides = [];
if (isset($data['overrides']) && is_array($data['overrides'])) {
    foreach ($data['overrides'] as $id => $v) {
        if (!is_string($id) && !is_int($id)) {
            continue;
        }
        $id = (string) $id;
        if (!preg_match('/^[a-zA-Z0-9_-]+$/', $id) || !is_array($v)) {
            continue;
        }
        if (!isset($v['lat']) || !isset($v['lon'])) {
            continue;
        }
        $lat = $v['lat'];
        $lon = $v['lon'];
        if (!is_numeric($lat) || !is_numeric($lon)) {
            continue;
        }
        $latF = (float) $lat;
        $lonF = (float) $lon;
        if ($latF < -90.0 || $latF > 90.0 || $lonF < -180.0 || $lonF > 180.0) {
            continue;
        }
        $overrides[$id] = ['lat' => $latF, 'lon' => $lonF];
    }
}

$hidden = [];
if (isset($data['hidden']) && is_array($data['hidden'])) {
    foreach ($data['hidden'] as $h) {
        if (is_string($h) && preg_match('/^[a-zA-Z0-9_-]+$/', $h)) {
            $hidden[] = $h;
        }
    }
}

$dir = __DIR__ . '/../../../../apps_data/demos-track';
if (!is_dir($dir) && !mkdir($dir, 0755, true)) {
    http_response_code(500);
    echo json_encode(['error' => 'cannot create storage directory']);
    exit;
}

$stateFile = $dir . '/state.json';

$fh = @fopen($stateFile, 'c');
if ($fh === false) {
    http_response_code(500);
    echo json_encode(['error' => 'cannot open state file']);
    exit;
}

if (!flock($fh, LOCK_EX)) {
    http_response_code(500);
    echo json_encode(['error' => 'cannot lock state file']);
    fclose($fh);
    exit;
}

$raw = stream_get_contents($fh);
$raw = $raw === false ? '' : $raw;
$state = [];
if ($raw !== '') {
    $decoded = json_decode($raw, true);
    if (is_array($decoded)) {
        $state = $decoded;
    }
}

$state[$course] = [
    'overrides' => $overrides ?: new stdClass(),
    'hidden' => $hidden,
    'updated_at' => gmdate('c'),
];

$flags = JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES;
$json = json_encode($state, $flags);
if ($json === false) {
    http_response_code(500);
    echo json_encode(['error' => 'cannot encode json: ' . json_last_error_msg()]);
    flock($fh, LOCK_UN);
    fclose($fh);
    exit;
}

ftruncate($fh, 0);
rewind($fh);
$written = fwrite($fh, $json);
fflush($fh);
flock($fh, LOCK_UN);
fclose($fh);

if ($written === false || $written !== strlen($json)) {
    http_response_code(500);
    echo json_encode(['error' => 'failed to write state']);
    exit;
}

echo json_encode(['ok' => true, 'course' => $course]);
