<?php
/**
 * Plugin Name: Chaba Boards
 * Description: Project CPTs for boards.surf-thailand.com (asset, expense,
 *              contact, reminder, bench, report, xlate, cam, render_job, news)
 *              + member-post translation + member-gated media endpoint.
 *              All CPTs are REST-writable (show_in_rest) so the
 *              fleet writers can create them via App Password. Meta keys are
 *              registered REST-writable AND shown as admin list columns.
 * Version: 0.3.2
 */

if (!defined('ABSPATH')) exit;

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
    ];
    foreach ($types as $slug => [$sing, $plural, $icon]) {
        $extra = [
            'label'      => $plural,
            'menu_icon'  => $icon,
            'rest_base'  => $slug,
        ];
        // news is a public feed surface: archive + standard taxonomies.
        if ($slug === 'news') {
            $extra['has_archive'] = true;
            $extra['taxonomies']  = ['category', 'post_tag'];
        }
        register_post_type($slug, array_merge($common, $extra));
    }
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
        'render_job' => ['kind' => 'Kind', 'status' => 'Status', 'model' => 'Model', 'size_px' => 'Size', 'secs' => 'Clip', 'duration_s' => 'Secs', 'backend' => 'Backend', 'est_cost_usd' => 'Est$', 'requested_by' => 'By'],
        'news'       => ['source_feed' => 'Feed', 'published_at' => 'Published'],
    ];
    return $cols[$type] ?? [];
}

foreach (['asset','expense','contact','reminder','bench','report','xlate','cam','render_job','news'] as $_t) {
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
    add_action("manage_{$_t}_posts_custom_column", function ($col, $post_id) {
        if (str_starts_with($col, 'chaba_')) {
            echo esc_html((string) get_post_meta($post_id, substr($col, 6), true));
        }
    }, 10, 2);
}
unset($_t);

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
