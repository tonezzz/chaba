<?php
/**
 * RView state API.
 *
 * GET  ?view_id=abc           -> state for view
 * GET  ?action=list           -> list all views
 * POST {action, view_id, ...} -> command
 */
header('Content-Type: application/json');

$dataDir = __DIR__ . '/../data';
$statePath = $dataDir . '/state.json';

if (!is_dir($dataDir)) {
    mkdir($dataDir, 0777, true);
}
if (!file_exists($statePath)) {
    file_put_contents($statePath, json_encode(['views' => []]));
    chmod($statePath, 0666);
}

function loadState()
{
    global $statePath;
    if (!file_exists($statePath)) {
        return ['views' => []];
    }
    $fp = fopen($statePath, 'r');
    if (!$fp) {
        return ['views' => []];
    }
    $raw = '';
    if (flock($fp, LOCK_SH)) {
        $size = filesize($statePath);
        $raw = $size > 0 ? fread($fp, $size) : '';
        flock($fp, LOCK_UN);
    }
    fclose($fp);
    $data = json_decode($raw, true);
    return is_array($data) ? $data : ['views' => []];
}

function saveState($data)
{
    global $statePath, $dataDir;
    if (!is_dir($dataDir)) {
        mkdir($dataDir, 0777, true);
    }
    $fp = fopen($statePath, 'c+');
    if (!$fp) {
        return false;
    }
    if (flock($fp, LOCK_EX)) {
        ftruncate($fp, 0);
        fwrite($fp, json_encode($data, JSON_PRETTY_PRINT));
        fflush($fp);
        flock($fp, LOCK_UN);
    }
    fclose($fp);
    chmod($statePath, 0666);
    return true;
}

function defaultStatus()
{
    return [
        'playing' => true,
        'volume' => 1.0,
        'muted' => false,
        'fullscreen' => false,
        'loop' => false,
        'shuffle' => false,
        'current_time' => 0,
        'duration' => null,
    ];
}

function nowIso()
{
    return gmdate('c');
}

function makeView($view_id, $display_name = null)
{
    return [
        'view_id' => $view_id,
        'display_name' => $display_name ?: $view_id,
        'created_at' => nowIso(),
        'updated_at' => nowIso(),
        'current' => null,
        'queue' => [],
        'history' => [],
        'status' => defaultStatus(),
    ];
}

function getView($data, $view_id, $create = true)
{
    if (!isset($data['views'][$view_id])) {
        if (!$create) {
            return null;
        }
        $data['views'][$view_id] = makeView($view_id);
    }
    return $data['views'][$view_id];
}

function putView(&$data, $view_id, $view)
{
    $data['views'][$view_id] = $view;
}

function inferMediaType($url)
{
    $lower = strtolower($url);
    if (preg_match('/\.(jpg|jpeg|png|gif|webp|svg|bmp|avif)($|[?#])/', $lower)) {
        return 'image';
    }
    if (preg_match('/\.(mp4|webm|ogg|mov|mkv|m4v)($|[?#])/', $lower)) {
        return 'video';
    }
    if (preg_match('/\.(mp3|wav|ogg|flac|aac|m4a|oga)($|[?#])/', $lower)) {
        return 'audio';
    }
    if (preg_match('/\.pdf($|[?#])/', $lower)) {
        return 'pdf';
    }
    if (strpos($lower, 'youtube.com/') !== false || strpos($lower, 'youtu.be/') !== false) {
        return 'iframe';
    }
    return 'iframe';
}

function send($data)
{
    echo json_encode($data);
    exit;
}

$method = $_SERVER['REQUEST_METHOD'];

if ($method === 'GET') {
    $data = loadState();
    if (isset($_GET['action']) && $_GET['action'] === 'list') {
        send([
            'ok' => true,
            'views' => array_map(function ($v) {
                return [
                    'view_id' => $v['view_id'],
                    'display_name' => $v['display_name'],
                    'current' => $v['current'],
                    'updated_at' => $v['updated_at'],
                ];
            }, $data['views']),
        ]);
    }
    if (isset($_GET['view_id'])) {
        $view = getView($data, $_GET['view_id'], true);
        $view['updated_at'] = nowIso();
        putView($data, $_GET['view_id'], $view);
        saveState($data);
        send(['ok' => true] + $view);
    }
    send(['ok' => false, 'error' => 'pass view_id or action=list']);
}

if ($method === 'POST') {
    $raw = file_get_contents('php://input');
    $body = json_decode($raw, true);
    if (!is_array($body)) {
        send(['ok' => false, 'error' => 'invalid JSON body']);
    }

    $action = $body['action'] ?? '';
    $view_id = $body['view_id'] ?? '';

    if (!$view_id && $action !== 'list') {
        send(['ok' => false, 'error' => 'view_id required']);
    }

    $data = loadState();

    if ($action === 'create') {
        $view = makeView($view_id, $body['display_name'] ?? null);
        putView($data, $view_id, $view);
        saveState($data);
        send(['ok' => true] + $view);
    }

    if ($action === 'delete') {
        unset($data['views'][$view_id]);
        saveState($data);
        send(['ok' => true, 'view_id' => $view_id, 'deleted' => true]);
    }

    if ($action === 'list') {
        send([
            'ok' => true,
            'views' => array_map(function ($v) {
                return [
                    'view_id' => $v['view_id'],
                    'display_name' => $v['display_name'],
                    'current' => $v['current'],
                    'updated_at' => $v['updated_at'],
                ];
            }, $data['views']),
        ]);
    }

    $view = getView($data, $view_id, true);

    if ($action === 'status') {
        send(['ok' => true] + $view);
    }

    if ($action === 'show') {
        if (empty($body['url'])) {
            send(['ok' => false, 'error' => 'url required for show']);
        }
        $item = [
            'url' => $body['url'],
            'title' => $body['title'] ?? '',
            'media_type' => ($body['media_type'] ?? 'auto') === 'auto'
                ? inferMediaType($body['url'])
                : $body['media_type'],
            'started_at' => nowIso(),
        ];
        if (!empty($body['enqueue'])) {
            $view['queue'][] = $item;
        } else {
            if ($view['current']) {
                $view['history'][] = $view['current'];
                if (count($view['history']) > 50) {
                    array_shift($view['history']);
                }
            }
            $view['current'] = $item;
            $view['status']['playing'] = true;
            $view['status']['current_time'] = 0;
        }
    } elseif ($action === 'queue') {
        $items = $body['items'] ?? [];
        foreach ($items as $i => $it) {
            if (isset($it['media_type']) && $it['media_type'] === 'auto') {
                $items[$i]['media_type'] = inferMediaType($it['url']);
            }
        }
        $mode = $body['mode'] ?? 'replace';
        if ($mode === 'replace') {
            $view['queue'] = $items;
        } else {
            $view['queue'] = array_merge($view['queue'], $items);
        }
    } elseif ($action === 'control') {
        $cmd = $body['command'] ?? '';
        $value = $body['value'] ?? null;
        switch ($cmd) {
            case 'play':
                $view['status']['playing'] = true;
                break;
            case 'pause':
                $view['status']['playing'] = false;
                break;
            case 'stop':
                $view['status']['playing'] = false;
                $view['status']['current_time'] = 0;
                break;
            case 'next':
                if (!empty($view['queue'])) {
                    if (!empty($view['status']['shuffle'])) {
                        $idx = array_rand($view['queue']);
                        $next = $view['queue'][$idx];
                        array_splice($view['queue'], $idx, 1);
                    } else {
                        $next = array_shift($view['queue']);
                    }
                    if ($view['current']) {
                        $view['history'][] = $view['current'];
                    }
                    $next['started_at'] = nowIso();
                    $view['current'] = $next;
                    $view['status']['playing'] = true;
                    $view['status']['current_time'] = 0;
                }
                break;
            case 'prev':
                if (!empty($view['history'])) {
                    $prev = array_pop($view['history']);
                    if ($view['current']) {
                        array_unshift($view['queue'], $view['current']);
                    }
                    $prev['started_at'] = nowIso();
                    $view['current'] = $prev;
                    $view['status']['playing'] = true;
                    $view['status']['current_time'] = 0;
                }
                break;
            case 'seek':
                $view['status']['current_time'] = is_numeric($value) ? (float) $value : 0;
                break;
            case 'volume':
                $view['status']['volume'] = is_numeric($value) ? (float) $value : 1.0;
                break;
            case 'fullscreen':
                $view['status']['fullscreen'] = (bool) $value;
                break;
            case 'loop':
                $view['status']['loop'] = (bool) $value;
                break;
            case 'shuffle':
                $view['status']['shuffle'] = (bool) $value;
                break;
            case 'clear_queue':
                $view['queue'] = [];
                break;
            default:
                send(['ok' => false, 'error' => 'unknown command: ' . $cmd]);
        }
    } else {
        send(['ok' => false, 'error' => 'unknown action: ' . $action]);
    }

    $view['updated_at'] = nowIso();
    putView($data, $view_id, $view);
    saveState($data);
    send(['ok' => true] + $view);
}

send(['ok' => false, 'error' => 'method not supported']);
