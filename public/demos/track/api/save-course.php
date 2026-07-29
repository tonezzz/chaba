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
if (!is_array($data) || !isset($data['course']) || !isset($data['yaml'])) {
    http_response_code(400);
    echo json_encode(['error' => 'invalid json']);
    exit;
}

$course = $data['course'];
$yaml = $data['yaml'];
if (!is_string($course) || !is_string($yaml) || !preg_match('/^[a-zA-Z0-9_-]+$/', $course)) {
    http_response_code(400);
    echo json_encode(['error' => 'invalid course name']);
    exit;
}

$coursesDir = realpath(__DIR__ . '/../courses');
if ($coursesDir === false) {
    http_response_code(500);
    echo json_encode(['error' => 'courses directory missing']);
    exit;
}

$file = $coursesDir . '/' . $course . '.yml';
if (strpos($file, $coursesDir . '/') !== 0) {
    http_response_code(400);
    echo json_encode(['error' => 'invalid course path']);
    exit;
}

$tmp = $file . '.tmp';
if (file_put_contents($tmp, $yaml) === false) {
    http_response_code(500);
    echo json_encode(['error' => 'cannot write temp file']);
    exit;
}

if (!rename($tmp, $file)) {
    @unlink($tmp);
    http_response_code(500);
    echo json_encode(['error' => 'cannot replace course file']);
    exit;
}

echo json_encode(['ok' => true, 'course' => $course]);
