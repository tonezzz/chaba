<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');

$coursesDir = __DIR__ . '/../courses';
$stateFile = __DIR__ . '/../../../../apps_data/track4/state.json';

$courses = [];

if (is_dir($coursesDir)) {
    foreach (glob($coursesDir . '/*.yml') as $file) {
        $name = basename($file, '.yml');
        if (preg_match('/^[a-zA-Z0-9_-]+$/', $name)) {
            $courses[$name] = ['name' => $name, 'saved' => false];
        }
    }
}

if (is_file($stateFile) && is_readable($stateFile)) {
    $raw = @file_get_contents($stateFile);
    if ($raw !== false && $raw !== '') {
        $state = @json_decode($raw, true);
        if (is_array($state)) {
            foreach ($state as $name => $data) {
                if (!is_string($name) || !preg_match('/^[a-zA-Z0-9_-]+$/', $name)) {
                    continue;
                }
                if (!is_array($data)) {
                    continue;
                }
                if (!isset($courses[$name])) {
                    $courses[$name] = ['name' => $name, 'saved' => true];
                } else {
                    $courses[$name]['saved'] = true;
                }
                $courses[$name]['updated_at'] = $data['updated_at'] ?? null;
            }
        }
    }
}

ksort($courses);

echo json_encode(array_values($courses), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
