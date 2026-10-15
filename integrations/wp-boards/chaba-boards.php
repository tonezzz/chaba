<?php
/**
 * Plugin Name: Chaba Boards
 * Description: Project CPTs for boards.surf-thailand.com (asset, expense,
 *              contact, reminder, bench, report, xlate, cam, render_job, news)
 *              + member-post translation + member-gated media endpoint.
 *              All CPTs are REST-writable (show_in_rest) so the
 *              fleet writers can create them via App Password. Meta keys are
 *              registered REST-writable AND shown as admin list columns.
 * Version: 0.4.1
 */

if (!defined('ABSPATH')) exit;

const CHABA_BOARDS_VER = '0.4.1';

// ============================================================================
// CPTs — member-visible records, private by post status (same model as the
// /chat/line/* pages: anonymous 404, logged-in members see them).
// ============================================================================

add_action('init', function () {
    $common = [
        'public'              => true,   // permalinks resolve; status gates who sees
        'show_in_rest'        => true,   // fleet writers create via REST
        'supports'            => ['title', 'editor', 'author', 'custom-fields', 'thumbnail', 'comments'],
        'has_archive'         => false,
        'menu_icon'           => 'dashicons-index-card',
        'show_in_menu'        => true,
    ];
    $types = [
        'asset'    => ['Asset',    'Assets',    'dashicons-car'],
        'expense'  => ['Expense',  'Expenses',  'dashicons-money-alt'],
        'contact'  => ['Contact',  'Contacts',  'dashicons-phone'],
        'reminder' => ['Reminder', 'Reminders', 'dashicons-bell'],
        'bench'    => ['Benchmark','Benchmarks','dashicons-chart-line'],
        'report'   => ['Report',   'Reports',   'dashicons-media-document'],
        'xlate'    => ['Translation','Translations','dashicons-translation'],
        'cam'      => ['Cam',       'Cams',      'dashicons-camera'],
        'render_job' => ['Render Job','Render Jobs','dashicons-format-image'],
        'news'     => ['News',      'News',      'dashicons-rss'],
        // repeat_ask — counted recurrences of Tony's requests
        // (docs/ssot/ssot.repeat-asks.yml synced by scripts/sync-repeat-asks.py)
        'repeat_ask' => ['Repeat Ask','Repeat Asks','dashicons-flag'],
        // lesson — Tony's education ledger: things he asked + the answers.
        // Agents write via REST; next_review drives spaced-recall digests.
        'lesson'   => ['Lesson',   'Lessons',   'dashicons-welcome-learn-more'],
    ];
    foreach ($types as $slug => [$sing, $plural, $icon]) {
        $extra = [
            'label'      => $plural,
            'menu_icon'  => $icon,
            'rest_base'  => $slug,
        ];
        // news is a public feed surface: archive + standard taxonomies +
        // hierarchical so distilled cluster posts can parent raw feed items.
        if ($slug === 'news') {
            $extra['has_archive']  = true;
            $extra['hierarchical'] = true;
            $extra['taxonomies']   = ['category', 'post_tag'];
            $extra['supports']     = array_merge($common['supports'],
                                                 ['page-attributes']);
        }
        // render_job + lesson get archives so members can re-browse:
        // /wp/render_job/ = results index, /wp/lesson/ = re-read ledger.
        if (in_array($slug, ['render_job', 'lesson'], true)) {
            $extra['has_archive'] = true;
        }
        register_post_type($slug, array_merge($common, $extra));
    }
});

// Rewrite rules only change on version bumps (new has_archive types) —
// flush once per deployed version, stored as an option so it never repeats.
add_action('init', function () {
    if (get_option('chaba_boards_ver') !== CHABA_BOARDS_VER) {
        flush_rewrite_rules();
        update_option('chaba_boards_ver', CHABA_BOARDS_VER, false);
    }
}, 20);

// ============================================================================
// 'archived' post status — 2nd-chance bin. WP trash auto-empties after 30d;
// anything we might want back goes status=archived instead (REST-writable via
// show_in_rest): hidden from front-end lists/searches, still in admin under
// the "Archived" filter. Cost: one row.
// ============================================================================
add_action('init', function () {
    register_post_status('archived', [
        'label'                     => 'Archived',
        'label_count'               => _n_noop('Archived <span class="count">(%s)</span>',
                                               'Archived <span class="count">(%s)</span>'),
        'public'                    => false,
        'exclude_from_search'       => true,
        'show_in_admin_all_list'    => true,
        'show_in_admin_status_list' => true,
        'show_in_rest'              => true,
    ]);
}, 5);

// ============================================================================
// Public-host canonicalization — CF fronts boards.surf-thailand.com and the
// Plesk host internally maps the request onto the boards.h3.gizmo-thailand.com
// vhost, so PHP sees HTTP_HOST=boards.h3 while X-Forwarded-Host carries the
// public name. WP builds some URLs (wp-admin canonical, list-table
// sort/pagination) straight from $_SERVER['HTTP_HOST'] — bypassing every URL
// filter — so rewrite the server vars at plugin-load time, before any URL is
// generated. Direct origin hits (no forwarded host) are left untouched.
if (($_SERVER['HTTP_X_FORWARDED_HOST'] ?? '') === 'boards.surf-thailand.com') {
    $_SERVER['HTTP_HOST']   = 'boards.surf-thailand.com';
    $_SERVER['SERVER_NAME'] = 'boards.surf-thailand.com';
    if (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https') {
        $_SERVER['HTTPS'] = 'on';
    }
}

// The origin stack rewrites REQUEST_URI to the index.php form internally:
// the public /wp/ arrives at WP as /wp/index.php/. That is fine for deep
// paths (permalink structure /index.php/%postname%/ expects it) but the front
// page's canonical URL is home_url('/') = /wp/ — so WP 301s /wp/index.php/
// back to /wp/, the upstream rewrites it again, and the edge sees an
// infinite self-redirect. Normalize ONLY the bare home URI; leave deep paths
// in the index.php form WP routing expects.
if (($_SERVER['REQUEST_URI'] ?? '') === '/wp/index.php/' || $_SERVER['REQUEST_URI'] === '/wp/index.php') {
    $_SERVER['REQUEST_URI'] = '/wp/';
}

// Belt for the same failure class: never 301 to the URL already requested.
// Genuine canonical redirects (missing slash, wrong scheme) keep working.
add_filter('redirect_canonical', function ($redirect_url, $requested_url) {
    $req = strtok((string) $requested_url, '?');
    $red = strtok((string) $redirect_url, '?');
    if ($req !== '' && $red !== '' && untrailingslashit($req) === untrailingslashit($red)) {
        return false;
    }
    return $redirect_url;
}, 10, 2);

// ============================================================================
// Public-host rewrite — belt-and-suspenders sweep: anything that still emits
// the origin host (plugins/themes reading stale state, URLs stored in content)
// gets rewritten to the public edge. With the HTTP_HOST override above, WP
// core already generates surf URLs natively; these filters only fire on URLs
// that somehow still carry boards.h3.
// ============================================================================
add_action('init', function () {
    $from = 'https://boards.h3.gizmo-thailand.com';
    $to   = 'https://boards.surf-thailand.com';
    $swap = function ($url) use ($from, $to) {
        return is_string($url) ? str_replace($from, $to, $url) : $url;
    };
    foreach (['admin_url', 'site_url', 'home_url', 'rest_url', 'login_url',
              'logout_url', 'lostpassword_url', 'register_url',
              'includes_url', 'content_url', 'plugins_url', 'network_site_url',
              'post_link', 'page_link', 'post_type_link', 'attachment_link',
              'term_link', 'get_pagenum_link', 'the_permalink', 'feed_link',
              'author_link', 'day_link', 'month_link', 'year_link',
              'wp_get_attachment_url'] as $f) {
        add_filter($f, $swap, 20);
    }
    // upload_dir returns an array, not a string
    add_filter('upload_dir', function ($d) use ($from, $to) {
        foreach (['url', 'baseurl'] as $k) {
            if (!empty($d[$k])) $d[$k] = str_replace($from, $to, $d[$k]);
        }
        return $d;
    }, 20);
});

// REST-writable meta — fleet writers set these via the `meta` field.
add_action('init', function () {
    $meta = [
        'asset'    => ['model', 'serial', 'purchase_date', 'warranty_until', 'vendor'],
        'expense'  => ['amount', 'currency', 'vendor', 'paid_by', 'receipt_date'],
        'contact'  => ['phone', 'line_id', 'role'],
        'reminder' => ['due_date', 'assignee'],
        'bench'    => ['suite', 'run_id', 'pass_count', 'fail_count', 'duration_s', 'commit'],
        'report'   => ['report_type', 'period', 'source_key'],
        'xlate'    => ['source_post', 'source_lang', 'target_lang', 'engine', 'status', 'chars'],
        'cam'      => ['camera_id', 'captured_at', 'kind', 'stream_url'],
        // render_job — one post per local/cloud render request, image AND
        // video (kind). Enough fields to spot regressions, compare settings
        // across runs, and track per-render cost. Image rows use the diffusion
        // params; video rows use secs/aspect/res/ref_url/operation/est_cost.
        // duration_s = wall-clock render time; secs = output clip length.
        // parent_job/chain_index link Veo extension chains (extend support).
        'render_job' => ['kind', 'prompt', 'negative_prompt', 'model',
                         'model_file', 'size_px', 'steps', 'sampler',
                         'cfg_scale', 'seed', 'duration_s', 'secs', 'vae_s',
                         'aspect', 'res', 'ref_url', 'operation',
                         'est_cost_usd', 'parent_job', 'chain_index',
                         'host', 'backend', 'status', 'requested_by',
                         'source', 'output_url', 'rating', 'error'],
        // news — feed provenance; dedup rides the deterministic slug
        // (n-<md5(link)>) so no GUID index is needed.
        'news'     => ['source_feed', 'source_url', 'published_at'],
        // repeat_ask — count = times re-asked; last_repeat = ISO date of most
        // recent recurrence (drives the admin list default sort).
        'repeat_ask' => ['topic', 'count', 'last_repeat', 'status'],
        // lesson — topic/level(intro|working|deep)/source(chat|voice|link)/
        // learned_at/next_review(ISO dates)/status(open|learned|revise)
        'lesson'   => ['topic', 'level', 'source', 'learned_at', 'next_review', 'status'],
        // pre-existing CPTs (registered elsewhere) — make their meta REST-writable too
        'place'    => ['coords', 'address', 'maps_url', 'osm_url'],
        'trip'     => ['start_date', 'end_date', 'travellers'],
    ];
    foreach ($meta as $type => $keys) {
        foreach ($keys as $k) {
            register_post_meta($type, $k, [
                'show_in_rest'      => true,
                'single'            => true,
                'type'              => 'string',
                'sanitize_callback' => 'sanitize_text_field',
                'auth_callback'     => function () { return current_user_can('edit_posts'); },
            ]);
        }
    }
});

// ============================================================================
// Admin list columns — registered meta is invisible in wp-admin without
// these; the CPT tables used to show only Title/Date ("fields show empty").
// First N meta keys per type become sortable-enough display columns.
// ============================================================================

function chaba_cpt_admin_columns(string $type): array {
    static $cols = [
        'asset'      => ['model' => 'Model', 'vendor' => 'Vendor', 'purchase_date' => 'Purchased', 'warranty_until' => 'Warranty'],
        'expense'    => ['amount' => 'Amount', 'currency' => 'Cur', 'vendor' => 'Vendor', 'paid_by' => 'Paid by', 'receipt_date' => 'Date'],
        'contact'    => ['role' => 'Role', 'phone' => 'Phone', 'line_id' => 'LINE'],
        'reminder'   => ['due_date' => 'Due', 'assignee' => 'Assignee'],
        'bench'      => ['suite' => 'Suite', 'run_id' => 'Run', 'pass_count' => 'Pass', 'fail_count' => 'Fail', 'duration_s' => 'Secs'],
        'report'     => ['report_type' => 'Type', 'period' => 'Period', 'source_key' => 'Source'],
        'xlate'      => ['source_lang' => 'From', 'target_lang' => 'To', 'engine' => 'Engine', 'status' => 'Status'],
        'cam'        => ['camera_id' => 'Camera', 'captured_at' => 'Captured', 'kind' => 'Kind'],
        'render_job' => ['result' => 'Result', 'prompt' => 'Prompt', 'status' => 'Status', 'model' => 'Model', 'size_px' => 'Size', 'secs' => 'Clip', 'duration_s' => 'Secs', 'est_cost_usd' => 'Est$', 'rating' => '★'],
        'news'       => ['source_feed' => 'Feed', 'published_at' => 'Published'],
        'repeat_ask' => ['count' => 'Asked', 'last_repeat' => 'Last repeat', 'status' => 'Status'],
        'lesson'     => ['level' => 'Level', 'learned_at' => 'Learned', 'next_review' => 'Review', 'status' => 'Status'],
    ];
    return $cols[$type] ?? [];
}

foreach (['asset','expense','contact','reminder','bench','report','xlate','cam','render_job','news','repeat_ask','lesson'] as $_t) {
    add_filter("manage_{$_t}_posts_columns", function ($cols) use ($_t) {
        $extra = [];
        foreach (chaba_cpt_admin_columns($_t) as $k => $label) {
            $extra["chaba_$k"] = $label;
        }
        // keep checkbox+title up front, date at the end
        $head = array_intersect_key($cols, ['cb' => 1, 'title' => 1]);
        $tail = array_intersect_key($cols, ['date' => 1]);
        return $head + $extra + $tail;
    });
    add_action("manage_{$_t}_posts_custom_column", function ($col, $post_id) use ($_t) {
        if (!str_starts_with($col, 'chaba_')) return;
        $k = substr($col, 6);
        $v = (string) get_post_meta($post_id, $k, true);
        // render_job: result = image/video thumb, prompt = readable excerpt
        if ($_t === 'render_job' && $k === 'result') {
            $u      = (string) get_post_meta($post_id, 'output_url', true);
            $status = (string) get_post_meta($post_id, 'status', true);
            if ($u === '') {
                // done/ok but nothing to show = a broken record, flag it
                echo in_array($status, ['done', 'ok'], true)
                    ? '<span title="status=' . esc_attr($status) . ' but no output_url">⚠ missing</span>'
                    : '<span style="opacity:.5">—</span>';
                return;
            }
            if (!preg_match('#^https?://#', $u)) {
                echo '<span title="' . esc_attr($u) . '">⚠ not a web URL</span>';
                return;
            }
            $kind = (string) get_post_meta($post_id, 'kind', true);
            echo $kind === 'video'
                ? '<a href="' . esc_url($u) . '" target="_blank">▶ video</a>'
                : '<a href="' . esc_url($u) . '" target="_blank"><img src="'
                  . esc_url($u) . '" style="width:64px;height:64px;object-fit:cover;border-radius:4px" loading="lazy"></a>';
            return;
        }
        if ($_t === 'render_job' && $k === 'prompt') {
            echo '<span title="' . esc_attr($v) . '">'
               . esc_html(mb_strimwidth($v, 0, 90, '…')) . '</span>';
            return;
        }
        echo esc_html($v);
    }, 10, 2);
}
unset($_t);

// repeat_ask admin list — sorted by last repeat by default; Asked/Last-repeat
// columns are clickable sortable (count numeric, last_repeat ISO-lexical).
add_filter('manage_edit-repeat_ask_sortable_columns', function ($cols) {
    $cols['chaba_count']       = 'ra_count';
    $cols['chaba_last_repeat'] = 'ra_last_repeat';
    return $cols;
});
add_action('pre_get_posts', function ($q) {
    if (!is_admin() || !$q->is_main_query()) return;
    if ($q->get('post_type') !== 'repeat_ask') return;
    $ob = $q->get('orderby');
    if ($ob === 'ra_count') {
        $q->set('meta_key', 'count');
        $q->set('orderby', 'meta_value_num');
        return;
    }
    if ($ob === 'ra_last_repeat') {
        $q->set('meta_key', 'last_repeat');
        $q->set('orderby', 'meta_value');
        return;
    }
    // default view: most recently repeated on top
    if (!$ob) {
        $q->set('meta_key', 'last_repeat');
        $q->set('orderby', 'meta_value');
        $q->set('order', 'DESC');
    }
});

// ============================================================================
// Member-post translation (TH<->EN) via Gemini — off unless CHABA_LLM_KEY set.
// ============================================================================

function chaba_llm_endpoint() {
    return defined('CHABA_LLM_ENDPOINT')
        ? CHABA_LLM_ENDPOINT
        : apply_filters('chaba_llm_endpoint', '');
}
function chaba_llm_key() {
    return defined('CHABA_LLM_KEY')
        ? CHABA_LLM_KEY
        : apply_filters('chaba_llm_key', '');
}

add_action('save_post_post', function ($post_id, $post, $update) {
    if (wp_is_post_revision($post_id) || wp_is_post_autosave($post_id)) return;
    if (get_post_meta($post_id, '_chaba_translation', true)) return; // once
    $src = trim(wp_strip_all_tags($post->post_title . "\n" . $post->post_content));
    if ($src === '' || mb_strlen($src) > 12000) return;

    $has_thai = (bool) preg_match('/[\x{0E00}-\x{0E7F}]/u', $src);
    $target   = $has_thai ? 'English' : 'Thai';
    $prompt   = "Translate the following to $target. "
              . "Keep markdown structure and names verbatim. Output ONLY the translation.\n\n$src";

    $endpoint = chaba_llm_endpoint();
    $key      = chaba_llm_key();
    if (!$endpoint || !$key) return;

    $resp = wp_remote_post($endpoint . '?key=' . rawurlencode($key), [
        'timeout' => 25,
        'headers' => ['Content-Type' => 'application/json'],
        'body'    => wp_json_encode([
            'contents' => [['parts' => [['text' => $prompt]]]],
            'generationConfig' => ['maxOutputTokens' => 2048, 'temperature' => 0.2],
        ]),
    ]);
    if (is_wp_error($resp)) return;
    $data = json_decode(wp_remote_retrieve_body($resp), true);
    $out  = $data['candidates'][0]['content']['parts'][0]['text'] ?? '';
    if (trim($out) === '') return;

    $job = [
        'post_title'  => sprintf('Xlate — %s (%s→%s)',
            $post->post_title, $has_thai ? 'th' : 'en', $has_thai ? 'en' : 'th'),
        'post_type'   => 'xlate',
        'post_status' => 'private',
    ];
    $jmeta = [
        'source_post' => (string) $post_id,
        'source_lang' => $has_thai ? 'th' : 'en',
        'target_lang' => $has_thai ? 'en' : 'th',
        'engine'      => 'gemini',
        'chars'       => (string) mb_strlen($src),
        'status'      => trim($out) === '' ? 'error' : 'ok',
    ];
    $jid = wp_insert_post($job);
    if ($jid && !is_wp_error($jid)) {
        foreach ($jmeta as $k => $v) update_post_meta($jid, $k, $v);
    }
    if (trim($out) === '') return;

    update_post_meta($post_id, '_chaba_translation', $out);
    update_post_meta($post_id, '_chaba_translation_lang', $has_thai ? 'en' : 'th');
}, 20, 3);

add_filter('the_content', function ($content) {
    if (!is_singular('post') || !in_the_loop() || !is_main_query()) return $content;
    $t = get_post_meta(get_the_ID(), '_chaba_translation', true);
    if (!$t) return $content;
    $lang = get_post_meta(get_the_ID(), '_chaba_translation_lang', true) === 'th' ? 'TH' : 'EN';
    return $content
        . '<details class="chaba-translation" style="margin-top:1em;border-top:1px solid #ddd;padding-top:.5em">'
        . '<summary style="cursor:pointer;opacity:.7">' . esc_html($lang) . ' translation</summary>'
        . '<div style="margin-top:.5em">' . wpautop(esc_html($t)) . '</div></details>';
});

add_action('add_meta_boxes', function () {
    add_meta_box('chaba-translation', 'Chaba translation', function ($post) {
        $t = get_post_meta($post->ID, '_chaba_translation', true);
        echo $t
            ? '<p><em>' . esc_html(mb_substr($t, 0, 140)) . '…</em></p>'
            . '<p><button class="button" name="chaba_retranslate" value="1">Re-translate</button></p>'
            : '<p>No translation yet. Saved posts translate automatically when the endpoint/key are set.</p>';
    }, 'post', 'side');
});
add_action('save_post_post', function ($post_id) {
    if (isset($_POST['chaba_retranslate'])) delete_post_meta($post_id, '_chaba_translation');
}, 5);

// ============================================================================
// Member-gated media delivery — /wp/v2/chaba/media/<id> streams an attachment
// only to logged-in members (read cap). Content-only images attached to private
// posts should be referenced by this endpoint instead of the direct uploads URL.
// NOTE: direct wp-content/uploads/ URLs stay public-by-URL until a docroot-level
// deny is added (Plesk: protected directory on uploads/, or nginx rule) —
// this endpoint is the access-controlled path, not a full block.
// ============================================================================

add_action('rest_api_init', function () {
    register_rest_route('chaba/v1', '/media/(?P<id>\d+)', [
        'methods'             => 'GET',
        'permission_callback' => function () { return is_user_logged_in(); },
        'callback'            => function ($req) {
            $id = (int) $req['id'];
            if (get_post_type($id) !== 'attachment') {
                return new WP_Error('bad_id', 'not an attachment', ['status' => 404]);
            }
            $path = get_attached_file($id);
            if (!$path || !file_exists($path)) {
                return new WP_Error('missing', 'file not found', ['status' => 404]);
            }
            $mime = get_post_mime_type($id) ?: 'application/octet-stream';
            nocache_headers();
            header('Content-Type: ' . $mime);
            header('Content-Length: ' . filesize($path));
            readfile($path);
            exit;
        },
    ]);
});

// ============================================================================
// render_job single view — the post content is usually empty; the record lives
// in meta. Render a job card: result media + prompt + negative + params table.
// Private posts already gate this to logged-in members.
// ============================================================================

add_filter('the_content', function ($content) {
    if (!is_singular('render_job') || !in_the_loop() || !is_main_query()) return $content;
    $id  = get_the_ID();
    $m   = function ($k) use ($id) { return trim((string) get_post_meta($id, $k, true)); };
    $out = $content;

    $u = $m('output_url');
    if ($u !== '' && preg_match('#^https?://#', $u)) {
        $out .= $m('kind') === 'video'
            ? '<p><video controls style="max-width:100%;border-radius:8px" src="' . esc_url($u) . '"></video></p>'
            : '<p><a href="' . esc_url($u) . '" target="_blank"><img src="' . esc_url($u)
              . '" style="max-width:100%;border-radius:8px" loading="lazy"></a></p>';
    } elseif ($u !== '') {
        $out .= '<p style="opacity:.7">⚠ output_url is a path, not a web URL — the file '
              . 'was never uploaded to WP: <code>' . esc_html($u) . '</code></p>';
    } elseif (in_array($m('status'), ['done', 'ok'], true)) {
        $out .= '<p style="opacity:.7">⚠ status is ' . esc_html($m('status'))
              . ' but no output_url was recorded.</p>';
    }
    if ($m('prompt') !== '') {
        $out .= '<blockquote style="border-left:3px solid #888;padding:.2em .8em;margin:.8em 0">'
              . nl2br(esc_html($m('prompt'))) . '</blockquote>';
    }
    if ($m('negative_prompt') !== '') {
        $out .= '<p><em>Negative:</em> ' . esc_html($m('negative_prompt')) . '</p>';
    }

    $rows = '';
    foreach (['kind' => 'Kind', 'status' => 'Status', 'model' => 'Model',
              'model_file' => 'Model file', 'size_px' => 'Size', 'aspect' => 'Aspect',
              'res' => 'Res', 'steps' => 'Steps', 'sampler' => 'Sampler',
              'cfg_scale' => 'CFG', 'seed' => 'Seed', 'secs' => 'Clip secs',
              'duration_s' => 'Render s', 'vae_s' => 'VAE s', 'backend' => 'Backend',
              'host' => 'Host', 'est_cost_usd' => 'Est $', 'rating' => 'Rating',
              'source' => 'Source', 'requested_by' => 'By', 'operation' => 'Op',
              'parent_job' => 'Parent', 'chain_index' => 'Chain#', 'error' => 'Error',
              'ref_url' => 'Ref'] as $k => $label) {
        $v = $m($k);
        if ($v === '') continue;
        $cell = ($k === 'ref_url')
            ? '<a href="' . esc_url($v) . '" target="_blank">link</a>'
            : esc_html($v);
        $rows .= '<tr><th style="text-align:left;padding:2px 10px 2px 0;opacity:.6;font-weight:600">'
               . esc_html($label) . '</th><td style="padding:2px 0">' . $cell . '</td></tr>';
    }
    if ($rows) {
        $out .= '<table style="font-size:.9em;margin-top:.8em">' . $rows . '</table>';
    }
    return $out;
});

// ============================================================================
// Lessons due — wp-admin dashboard widget so review dates surface without a
// cron: next_review <= today AND status != learned.
// ============================================================================

add_action('wp_dashboard_setup', function () {
    wp_add_dashboard_widget('chaba-lessons-due', 'Chaba — lessons due & broken renders', function () {
        // broken render_jobs: status done/ok but output_url missing or not a
        // web URL — zero-cost counter computed on dashboard load.
        $bad = 0; $total = 0; $bad_ids = [];
        $jobs = get_posts(['post_type' => 'render_job', 'post_status' => 'any',
                           'posts_per_page' => -1, 'fields' => 'ids']);
        foreach ($jobs as $jid) {
            $total++;
            $u = (string) get_post_meta($jid, 'output_url', true);
            $s = (string) get_post_meta($jid, 'status', true);
            if (in_array($s, ['done', 'ok'], true)
                && ($u === '' || !preg_match('#^https?://#', $u))) {
                $bad++; $bad_ids[] = $jid;
            }
        }
        printf('<p><strong>Render jobs:</strong> %d total, %d broken output%s</p>',
            $total, $bad,
            $bad ? ' — <a href="' . esc_url(admin_url('edit.php?post_type=render_job')) . '">review</a>' : ' ✓');
        echo '<hr style="border:none;border-top:1px solid #ddd;margin:.6em 0">';
        $q = new WP_Query([
            'post_type'      => 'lesson',
            'post_status'    => 'any',
            'posts_per_page' => 10,
            'meta_key'       => 'next_review',
            'orderby'        => 'meta_value',
            'order'          => 'ASC',
            'meta_query'     => [[
                'key'     => 'next_review',
                'value'   => current_time('Y-m-d'),
                'compare' => '<=',
                'type'    => 'DATE',
            ], [
                'key'     => 'status',
                'value'   => 'learned',
                'compare' => '!=',
            ]],
        ]);
        if (!$q->have_posts()) { echo '<p>Nothing due. ✓</p>'; return; }
        echo '<ul>';
        foreach ($q->posts as $p) {
            printf('<li><a href="%s">%s</a> <span style="opacity:.6">— %s</span></li>',
                esc_url(get_edit_post_link($p->ID)),
                esc_html(get_the_title($p)),
                esc_html((string) get_post_meta($p->ID, 'next_review', true)));
        }
        echo '</ul>';
    });
});

// ============================================================================
// Prompt assist — render_job editor box: sends the prompt to the existing
// free Gemini lane (CHABA_LLM_ENDPOINT/KEY, same as xlate) and returns an
// analysis + suggested rewrite + negative-prompt hints. Advisory only —
// Tony reads/copies; nothing is written back automatically.
// ============================================================================

add_action('add_meta_boxes', function () {
    add_meta_box('chaba-prompt-assist', 'Prompt assist (free Gemini)', function ($post) {
        $prompt = get_post_meta($post->ID, 'prompt', true);
        echo '<p><button type="button" class="button" id="chaba-pa-btn"'
           . ($prompt ? '' : ' disabled') . '>Analyze &amp; suggest</button>'
           . ' <span id="chaba-pa-status" style="opacity:.6"></span></p>'
           . '<div id="chaba-pa-out" style="white-space:pre-wrap;font-size:.9em"></div>'
           . '<script>(function(){var b=document.getElementById("chaba-pa-btn");if(!b)return;'
           . 'b.onclick=function(){var s=document.getElementById("chaba-pa-status"),o=document.getElementById("chaba-pa-out");'
           . 's.textContent="asking…";o.textContent="";var f=new FormData();'
           . 'f.append("action","chaba_prompt_assist");f.append("post_id","' . (int) $post->ID . '");'
           . 'f.append("_wpnonce","' . wp_create_nonce('chaba_prompt_assist') . '");'
           . 'fetch(ajaxurl,{method:"POST",body:f,credentials:"same-origin"}).then(function(r){return r.json();})'
           . '.then(function(j){s.textContent="";o.textContent=j.success?j.data:(j.data||"failed");})'
           . '.catch(function(e){s.textContent="error "+e;});};})();</script>';
    }, 'render_job', 'normal', 'high');
});

add_action('wp_ajax_chaba_prompt_assist', function () {
    if (!current_user_can('edit_posts')) wp_die('forbidden', 403);
    check_ajax_referer('chaba_prompt_assist');
    $post_id = (int) ($_POST['post_id'] ?? 0);
    $prompt  = trim((string) get_post_meta($post_id, 'prompt', true));
    if ($prompt === '') wp_send_json_error('no prompt on this job', 400);
    $endpoint = chaba_llm_endpoint();
    $key      = chaba_llm_key();
    if (!$endpoint || !$key) wp_send_json_error('CHABA_LLM endpoint/key not set', 503);

    $ask = "You are a diffusion-prompt coach. Analyze this generation prompt and reply "
         . "in PLAIN TEXT with four short sections:\n"
         . "ISSUES — what is vague, conflicting, or likely to hurt quality\n"
         . "SUGGESTED PROMPT — an improved rewrite (keep intent + language)\n"
         . "NEGATIVE PROMPT — 3-8 comma-separated terms worth excluding\n"
         . "PARAMS — suggested steps/cfg/sampler for a fast local SDXL-class model\n\n"
         . "Prompt:\n" . mb_substr($prompt, 0, 4000);

    $resp = wp_remote_post($endpoint . '?key=' . rawurlencode($key), [
        'timeout' => 30,
        'headers' => ['Content-Type' => 'application/json'],
        'body'    => wp_json_encode([
            'contents' => [['parts' => [['text' => $ask]]]],
            'generationConfig' => ['maxOutputTokens' => 1024, 'temperature' => 0.4],
        ]),
    ]);
    if (is_wp_error($resp)) wp_send_json_error('request failed: ' . $resp->get_error_message(), 502);
    $data = json_decode(wp_remote_retrieve_body($resp), true);
    $out  = trim($data['candidates'][0]['content']['parts'][0]['text'] ?? '');
    $out === '' ? wp_send_json_error('empty model response', 502)
                : wp_send_json_success($out);
});
