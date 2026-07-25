<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');

$course = $_REQUEST['course'] ?? '';
if ($course === '' || !preg_match('/^[a-zA-Z0-9_-]+$/', $course)) {
    http_response_code(400);
    echo json_encode(['error' => 'missing or invalid course']);
    exit;
}

$dir = __DIR__ . '/../../../../apps_data/track3';
$stateFile = $dir . '/state.json';

if (!is_dir($dir) || !file_exists($stateFile) || !is_readable($stateFile)) {
    echo json_encode(['overrides' => new stdClass(), 'hidden' => []]);
    exit;
}

$raw = @file_get_contents($stateFile);
$state = [];
if ($raw !== false) {
    $decoded = json_decode($raw, true);
    if (is_array($decoded)) {
        $state = $decoded;
    }
}

$data = $state[$course] ?? [];

$overrides = [];
if (isset($data['overrides']) && is_array($data['overrides'])) {
    foreach ($data['overrides'] as $id => $v) {
        if (!is_string($id) || !preg_match('/^[a-zA-Z0-9_-]+$/', $id) || !is_array($v)) {
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

echo json_encode([
    'overrides' => $overrides ?: new stdClass(),
    'hidden' => $hidden,
]);
