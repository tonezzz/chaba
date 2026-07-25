<?php
header('Content-Type: text/plain; charset=utf-8');

$dir = __DIR__ . '/../apps_data/track3';

echo "script_dir: " . __DIR__ . "\n";
echo "target: $dir\n";
echo "realpath_before: " . (realpath($dir) ?: 'not yet') . "\n";
echo "open_basedir: " . ini_get('open_basedir') . "\n";
echo "disable_functions: " . ini_get('disable_functions') . "\n";
echo "user/uid: " . get_current_user() . ' / ' . getmyuid() . "\n";

$ok = @mkdir($dir, 0775, true);
echo "mkdir_ok: " . ($ok ? 'yes' : 'no') . "\n";
$err = error_get_last();
if ($err && $err['message']) {
    echo "mkdir_error: " . $err['message'] . "\n";
}

echo "realpath_after: " . (realpath($dir) ?: 'still missing') . "\n";
echo "is_dir: " . (is_dir($dir) ? 'yes' : 'no') . "\n";
echo "is_writable: " . (is_writable($dir) ? 'yes' : 'no') . "\n";

if (is_dir($dir)) {
    $file = $dir . '/hello.txt';
    $written = @file_put_contents($file, 'track3:' . date('c'));
    echo "file_put: " . ($written !== false ? "ok ($written bytes)" : 'failed') . "\n";
    echo "file_read: " . (is_readable($file) ? file_get_contents($file) : 'not readable') . "\n";
    echo "dir_perms: " . substr(sprintf('%o', fileperms($dir)), -4) . "\n";
    echo "file_perms: " . (is_file($file) ? substr(sprintf('%o', fileperms($file)), -4) : 'n/a') . "\n";
}
