<?php
/**
 * usage-pull-cron.php — Plesk Scheduled Task entry point for the
 * chaba-boards usage pull-render worker (card
 * wp-usage-pull-render-plesk-worker, OPS-0661).
 *
 * Ships inside the chaba-boards plugin directory. Not a WP plugin file
 * itself — it's the CLI shim a Plesk "Run a PHP script" task executes:
 *
 *   Plesk > Scheduled Tasks > Run a PHP script
 *   Script path: wp-content/plugins/chaba-boards/usage-pull-cron.php
 *   Schedule:    every 15 min
 *
 * wp-cli equivalent (Plesk WP Toolkit ships wp-cli per site):
 *   wp --path=<wp-root> eval 'chaba_usage_pull_run();'
 *
 * Finds wp-load.php by walking up from this file
 * (.../wp/wp-content/plugins/chaba-boards/usage-pull-cron.php -> wp root
 * is three levels up — /wp subdir installs included), loads WP, runs the
 * worker, prints one summary line into the task log.
 */

if (PHP_SAPI !== 'cli' && PHP_SAPI !== 'phpdbg') {
    http_response_code(404);
    exit('cli only');
}

$dir = __DIR__;
$wp_load = null;
for ($i = 0; $i < 6; $i++) {
    $cand = $dir . '/wp-load.php';
    if (file_exists($cand)) { $wp_load = $cand; break; }
    $dir = dirname($dir);
}
if (!$wp_load) {
    fwrite(STDERR, "usage-pull: wp-load.php not found above " . __FILE__ . "\n");
    exit(1);
}

define('WP_USE_THEMES', false);
require $wp_load;

if (!function_exists('chaba_usage_pull_run')) {
    fwrite(STDERR, "usage-pull: chaba-boards plugin not loaded "
        . "(inactive or missing)\n");
    exit(1);
}

echo 'usage-pull ' . chaba_usage_pull_run() . "\n";
