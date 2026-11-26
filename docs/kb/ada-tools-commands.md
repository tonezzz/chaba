# Ada tools command reference

Generated: 2026-11-23 00:38 UTC by `scripts/ada/tools-commands-catalog.py` — **do not edit**. Regenerate after any tool-declaration change (`backend/realtime_provider.py`, `backend/tools.d/*`, `manifest.yml`, `tool_guide.yml`, `_ALIASES`, `ssot.tool-surface.yml`, scenarios):

```
python3 scripts/ada/tools-commands-catalog.py          # write
python3 scripts/ada/tools-commands-catalog.py --check  # CI gate
```

<!-- tools-commands:auto -->

Source: ada-voice@6a39e3a (2026-11-19) — ⚠ ada-voice checkout is 7 commit(s) behind origin/main; pull and regen for a live surface. Surface: **37** builtin · **31** drop-in · **3** guest (Chaba) · **92** absorbed aliases across **29** merge families (cap 112, consolidation target 38).

Companion machine snapshot: `docs/kb/ada-tools-commands.json` (the Ada *what-can-you-do* verb reads that file — contract in `docs/kb/ada-tools-verb-contract.md`). `‡` marks the canonical seat of a tools-merge-* family.

## Builtin tools (37)

Declared inline in `backend/realtime_provider.py` — ship on the Gemini Live wire every session (lazy = name+blurb+skeleton only).

| tool | purpose | triggers (scenario utterances) | backend | cost/policy | last changed |
|---|---|---|---|---|---|
| `ada_camera_snapshot` ‡camera | Take a still camera snapshot — property CCTV (source='vms'), home cams, or Thailand traffic cams (source='traffic'; 'auto' picks by args). | Can you take a look at the swimming pool camera and tell …<br>And how about the tennis court — does it look wet there? | vms | confirmed · lazy-schema · +guide | 2026-10-12 |
| `ada_enroll_speaker` ‡meta_voice_enroll | Enroll the current speaker's voice from buffered audio (who='speaker') or register a visitor name (who='guest'). | Please enroll my voice — call me guard-tester.<br>Actually, enroll my voice again but as guard-tester-two t… | speaker | confirmed · lazy-schema · +guide | 2026-10-13 |
| `ada_forget` | Retract a memory (bank= + key=) — it stops surfacing in recall but stays in the archive for audit. | — | mddb | confirmed · lazy-schema · +guide | 2026-10-13 |
| `ada_memory_search` ‡memory_search | Search memory — curated banks, sessions, guest notes (absorbs guest_recall); scope=/bank= pick the store. | Research additional ideas for my lab stack plan. Search t… | mddb | read · full-schema · +guide | 2026-10-13 |
| `ada_ops` ‡meta_voice_ops | Ops/meta — outcome\|usage\|health\|check\|research\|report\|acl_explain — see tool_guide; | — | exec | confirmed · lazy-schema · +guide | 2026-10-13 |
| `ada_persona` ‡meta_voice_persona | Read/adjust a speaker's style preferences — action=set\|show\|reset\|list, person= targets another member. | Ada, from now on talk to me more formally — polite and co… | exec | read · lazy-schema · +guide | 2026-10-13 |
| `ada_remember` ‡memory_remember | Store or update a memory (absorbs vocab_note, guest_remember*, report_habit_observation) — bank= + kind=; a matching key/subject+attribute updates ... | Research additional ideas for my lab stack plan. Search t…<br>Remember that my coffee machine plug is called coffee plug. | mddb | confirmed · lazy-schema · +guide | 2026-10-13 |
| `ada_resolve_action` | Mark a pending action proposal applied or dismissed — key= from the pending-suggestions list after the user decides. | — | conversation_memory | read · lazy-schema · +guide | 2026-10-13 |
| `ada_session_recall` ‡memory_recall | Recall past voice conversations (scope='sessions', background ~20s) or stored HA memory (scope='history', absorbs ada_ha_recall). | — | exec | read · lazy-schema · +guide | 2026-10-13 |
| `calendar_read` ‡calendar_read | Calendar reads — action='events'\|'calendars'\|'freebusy' (absorbs calendar_list_*/calendar_freebusy); | — | google | read · full-schema · +guide | 2026-10-13 |
| `calendar_write` ‡calendar_write | Calendar writes — action='create'\|'delete'\|'shift' (move overdue items to a new day; absorbs calendar_create/delete/shift_*). | — | google | confirmed · lazy-schema · +guide | 2026-10-13 |
| `cast_to_screen` ‡cast_to_screen | Drive the numbered vcast displays (browser/PWA — NOT the TV; absorbs vcast_say/list/status/shortcut + claim/assign/background). | Play this YouTube video on screen {real_screen}: https://…<br>Play the dub test mp4 on screen {real_screen} — slash app… | vcast | confirmed · full-schema · +guide | 2026-10-13 |
| `cctv_wall` | Show a live camera wall (periodic thumbnail grid) for a zone on a vcast display — action='start'\|'stop'\|'settings'\|'status'. | — | vcast | confirmed · full-schema · +guide | 2026-10-13 |
| `chat_send` ‡chat_send | Send a LINE/Telegram/webchat message in the background — 'queued' returns first, the outcome lands later as a system note. | — | line/tg | read · full-schema · +guide | 2026-10-14 |
| `cms_edit` ‡cms_edit | Miniapp edits — action='note' (append a timeline note, free) \| 'delete' (confirmed) \| 'automate' (registry ops: op=list/get free, set/enable/disabl... | — | wp-boards | confirmed · lazy-schema · +guide | 2026-10-13 |
| `cms_publish_page` | Create or fully replace a miniapp page (slug is its id; an existing slug overwrites). | Update it — the water is now up to the gate, and power is…<br>Good — publish that as a page titled Hosting Provider Ass… | wp-boards | confirmed · lazy-schema · +guide | 2026-10-13 |
| `cms_read` ‡cms_read | Read miniapp pages and reports — action='list'\|'search'\|'get'\|'verify'. | — | mddb | read · full-schema · +guide | 2026-10-13 |
| `control_entity` ‡ha_control | Actuate one Home Assistant entity (absorbs control_cover, press_button, control_media_player) — on=/action= picked by the entity's domain. | — | ha | confirmed · full-schema · +guide | 2026-10-13 |
| `devin` ‡devin | Devin session control — action='dispatch' (new unattended session) \| 'followup' (message a session) \| 'answer' (reply to a blocked job). | — | mddb | confirmed · lazy-schema · +guide | 2026-10-14 |
| `devin_read` ‡devin_read | Devin job ledger — action='status'\|'jobs'\|'pending'\|'report'\|'review' (absorbs devin_status/jobs/pending/job_report and ada_devteam_review; | I'd like a new tool that tells me how many Devin sessions… | mddb | read · lazy-schema · +guide | 2026-10-13 |
| `docs` ‡docs | Personal document archive (deeds, IDs, passports, receipts — absorbs ada_doc_*) — action='search'\|'get'\|'print'\|'archive'; | — | mddb | confirmed · full-schema · +guide | 2026-10-13 |
| `drive` ‡drive | The operator's Google Drive — action='search'\|'show'\|'get'\|'update' (absorbs drive_*; for archived deed/ID sets use docs action='search'). | — | gdrive | confirmed · lazy-schema · +guide | 2026-10-13 |
| `get_home_state` ‡ha_state | Read-only home state — plugs, occupancy, habit conditions (absorbs ada_ha_get_state). | — | ha | read · lazy-schema · +guide | 2026-10-13 |
| `get_rk600_weather` | Local RK600 weather station readings — wind, temperature, humidity, pressure, rainfall. | — | exec | read · lazy-schema · +guide | 2026-10-13 |
| `gev_command` ‡gev | Drive God's Eye View (the Cesium map at /apps/gev/) on connected screens — name+args per the GEV schema. | — | gev | confirmed · lazy-schema · +guide | 2026-10-13 |
| `ha_confidence` ‡ha_confidence | Device trust/safety registry (absorbs ada_ha_*_device_confidence) — no args lists devices by confidence+safety; | — | ha | read · lazy-schema · +guide | 2026-10-13 |
| `home_history` ‡ha_history | HA history/event reads — kind='logbook'\|'events'\|'timeline'\|'series'\|'snapshots' (absorbs get_logbook, get_sensor_history, get_entity_events, get_r... | — | ha | read · lazy-schema · +guide | 2026-10-13 |
| `home_search` ‡ha_search | Find HA devices, sensors, or recorded events — kind='device'\|'sensor'\|'event' (absorbs the list/search/ada_ha_search_* tools); blank query lists th... | — | ha | read · lazy-schema · +guide | 2026-10-13 |
| `home_status` ‡home_status | Merged home-status reads — what='battery'\|'power'\|'inverter'\|'pool'\|'dashboard'\|'habit' (absorbs the get_*_status getters). | — | ha | read · lazy-schema · +guide | 2026-10-13 |
| `plan_day` ‡plan_day | Merged day view or weekly digest — period='today'\|'tomorrow'\|'week', day= overrides the target (absorbs ada_daily_summary/ada_weekly_comparison). | — | google | read · lazy-schema · +guide | 2026-10-13 |
| `set_facial_expression` | Changes Ada's visible facial expression without interrupting speech. | — | exec | read · full-schema | 2026-10-13 |
| `tasks` ‡tasks | Task list ops — action='add'\|'list'\|'done'\|'move' (absorbs tasks_*). | — | google | confirmed · lazy-schema · +guide | 2026-10-13 |
| `tv_action` | Send a command to the LG TV's cast-browser via HA rest_command.tv_action — cmd=nav\|scroll\|click\|type\|press\|back\|shot\|viewport\|power, payload in text=. | Put google dot com on the TV.<br>Scroll down on the TV. | ha | confirmed · lazy-schema · +guide | 2026-10-13 |
| `vcast_gesture` | Enable/disable gesture control on a vcast display — mode='room' (wake-on-motion), 'hand' (hand tracking), 'off'. | — | vcast | read · lazy-schema · +guide | 2026-10-13 |
| `vcast_snapshot` ‡vcast_snapshot | Capture what a vcast display is actually showing — verify after a cast instead of trusting the reported state flag. | — | vcast | read · lazy-schema · +guide | 2026-10-13 |
| `web_search` | Search the public internet for current facts — news, prices, forecasts. | Now check online whether anything important changed on th…<br>Search DuckDuckGo for the latest Bangkok flood news. | gemini-grounded | read · lazy-schema · +guide | 2026-10-13 |
| `yt` ‡yt | YouTube/media on the living-room TV — action='cast' PLAYS a video (.mp4/.m3u8 URL or search phrase) only on an explicit play request — 'find a clip... | — | vcast | read · lazy-schema · +guide | 2026-10-13 |

## Drop-in tools (31)

`backend/tools.d/` modules gated by `manifest.yml` (policy/timeout/secondary).

| tool | purpose | triggers (scenario utterances) | backend | cost/policy | last changed |
|---|---|---|---|---|---|
| `ada_adobe_stock` | Adobe Stock campaign QC — status/decide/repair_info. | — | picker-server | read · 30s · +guide | 2026-11-08 |
| `ada_device_acl` | Manage per-identity device ACL grants — owner only. | — | exec | owner_only · 10s · +guide | 2026-10-12 |
| `ada_lesson` | Save knowledge to Education (the WP lesson CPT) through board-api. | — | board-api | confirmed · 60s · +guide | 2026-11-07 |
| `ada_look` | What the /apps/eye/ page's in-browser detector sees right now — 'what do you see' while an eye page publishes. | — | mddb | read · 10s · 2nd-ok · +guide | 2026-10-12 |
| `ada_market_quote` | Market prices from our trade database — kind='fx'\|'gold'\|'dxy'\|'oil'\|'silver'\|'copper'\|'natural_gas'. | — | trade-api | read · 20s · 2nd-ok · +guide | 2026-10-12 |
| `ada_member_keys` | Member PWA invites + key approval — owner only. | — | exec | owner_only · 15s · +guide | 2026-10-12 |
| `ada_opencode` | Ada/OpenCode control plane — action='preflight'\|'status'\|'receipts'. | Ada, preflight the OpenCode work for card ADA-1010 withou… | exec | read · 30s · +guide | 2026-11-08 |
| `ada_opencode_dispatch` | Queue a preflight-approved OpenCode job for an exact card. | Ada, dispatch the approved OpenCode job for card ada-open… | board-api | confirmed · 45s · +guide | 2026-11-08 |
| `ada_render_image` | Generate an image from a prompt, or edit source photos (ref_url/ref_urls, 'last' = the previous render) with instructions, and return a shareable i... | — | exec | read · 120s · +guide | 2026-10-15 |
| `ada_render_video` | Render a short video clip from a prompt (optionally animating the ref_url image) and return a playable clip URL. | — | wp-boards | read · 220s · +guide | 2026-10-15 |
| `ada_sweep` | Batch-process eligible backlog cards: preflight each executor-tagged card, report per-card gaps, and queue the ready ones under this single confirm... | — | board-api | confirmed · 120s · +guide | 2026-11-07 |
| `ada_track_device` | Locate a device or list the tracked fleet — merges HA device_tracker, the telemetry beacon, tailnet, and the LAN scan. | — | mddb | owner_only · 30s · +guide | 2026-10-12 |
| `conv_journal` | Build a conversation report page (text + media) from the LINE room journal into the CMS — recall 'what did we discuss' later. | — | mddb | read · 120s · 2nd-ok · +guide | 2026-10-12 |
| `cpt_post` | Save a structured record on the boards WP site — receipt/expense photo -> expense, 'save this contact' -> contact, 'remind us' -> reminder, 'asset:... | — | wp-boards | read · 60s · 2nd-ok · +guide | 2026-10-16 |
| `devnest_news` | Publish one verified, source-backed public DevNest News article through board-api into the MediaWiki News hierarchy. | — | board-api | confirmed · 60s | 2026-11-06 |
| `devnest_news_diagnose` | Diagnose a protected DevNest News promotion without publishing. | — | board-api | read · 60s | 2026-11-06 |
| `devnest_news_review` | Read one protected PrivateNews review page through board-api. | — | board-api | read · 60s | 2026-11-06 |
| `doc_read` | Read a document the user sent on LINE (the /relay-img/arch/ URL from a 'document received' note, or an archive path) and extract what prompt asks f... | — | exec | read · 60s · 2nd-ok · +guide | 2026-10-13 |
| `gs_capture_eval` | Evaluate a local image set for Gaussian Splat capture readiness using the deterministic read-only evaluator. | — | mcp | read · 60s · 2nd-ok | 2026-11-07 |
| `kanban` ‡kanban | Kanban board — action='next'\|'next_choice'\|'list'\|'read'\|'comment'\|'move'\|'queue'\|'ask'\|'file'\|'respond'. | — | board-api | read · 180s · 2nd-ok · full-schema · +guide | 2026-11-07 |
| `nest_status` | Live DevNest queue + KK-Mac worker status: per-lane verdicts, heartbeat, pack counts. | — | nest-queue-health | read · 20s · 2nd-ok | 2026-11-09 |
| `page_snapshot` | Screenshot a web page into a sendable image — returns image_url for chat_send. | — | playlived | read · 90s · 2nd-ok · +guide | 2026-10-12 |
| `percussion` | Nest percussion display music layer: style/mood/instruments. | — | input-bridge | owner_only · 10s · +guide | 2026-10-12 |
| `place_report` | Turn a Google Maps link or place name into a public WordPress report post (map image + links); | — | wp-boards | read · 60s · 2nd-ok · +guide | 2026-10-14 |
| `speaker_profiles` | Enrolled voiceprint admin — action='list'\|'match'\|'remove'\|'re-enroll'\|'alias'\|'match_file'\|'enroll_file'. | — | exec | read · 60s · 2nd-ok · +guide | 2026-10-13 |
| `trip_calendar` | Generate a trip-calendar page family (rollup + daily leaf pages) and return the link — use for 'show my trip calendar'. | — | chaba | read · 120s · 2nd-ok · +guide | 2026-10-13 |
| `voice_fx` | Sci-fi narration / voice FX settings (sci_fx master + sys_ops flags; action='status'/'set'). | — | exec | read · 5s · 2nd-ok · +guide | 2026-10-12 |
| `weather_station` | Live readings from the RK600 station at Michael's site: wind kt+dir, temp, humidity, rain. | — | rikacloud-api | read · 20s · 2nd-ok · +guide | 2026-10-19 |
| `wiki_extension` | List or manage the approved MediaWiki extension bundle through board-api. | — | board-api | confirmed · 120s | 2026-11-04 |
| `wp_chat_page` | Create/update a member's private webchat page on the boards WP site under /chat/ — embeds the ada-webchat widget on their lane. | — | wp-boards | read · 60s · 2nd-ok | 2026-10-14 |
| `wp_post` | Post a free-form entry to a member's WordPress page on the boards site (persons: tony, kk, nhong) — webboard/'ลงเว็บ' asks. | — | wp-boards | read · 60s · 2nd-ok · +guide | 2026-10-16 |

## Guest (Chaba) surface (3)

`CHABA_DECLARATIONS` — guest-scoped re-declarations of canonical names for the visitor surface; params pinned (e.g. kind='guest').

| tool | purpose | triggers (scenario utterances) | backend | cost/policy | last changed |
|---|---|---|---|---|---|
| `ada_enroll_speaker` ‡meta_voice_enroll | Register the visitor's name for later admin promotion — always who='guest'; | Please enroll my voice — call me guard-tester.<br>Actually, enroll my voice again but as guard-tester-two t… | speaker | confirmed · +guide | 2026-10-12 |
| `ada_memory_search` ‡memory_search | Search public guest memories by keyword — always scope='guest'. | Research additional ideas for my lab stack plan. Search t… | mddb | read · full-schema · +guide | 2026-10-12 |
| `ada_remember` ‡memory_remember | Save a public guest memory under the visitor's name — always kind='guest'; | Research additional ideas for my lab stack plan. Search t…<br>Remember that my coffee machine plug is called coffee plug. | mddb | confirmed · +guide | 2026-10-12 |

## Merge families (tools-merge-*)

Absorbed names route to the canonical seat through `tool_runner._ALIASES`; `pending` = absorbed name still declared on the surface.

| family | canonical | absorbed | status | card | scenario |
|---|---|---|---|---|---|
| camera | `ada_camera_snapshot` | `cctv_snapshot`, `traffic_camera` | merged | tools-merge-camera | tool_merge_camera |
| cms_read | `cms_read` | `cms_list_pages`, `cms_get_page`, `cms_verify_page` | merged | tools-merge-cms | tool_merge_cms |
| cms_edit | `cms_edit` | `cms_note_update`, `cms_delete_page`, `cms_automation` | merged | tools-merge-cms | tool_merge_cms |
| calendar_read | `calendar_read` | `calendar_list_events`, `calendar_list_calendars`, `calendar_freebusy` | merged | tools-merge-calendar-plan | tool_merge_calendar_plan |
| calendar_write | `calendar_write` | `calendar_create_event`, `calendar_delete_event`, `calendar_shift_overdue` | merged | tools-merge-calendar-plan | tool_merge_calendar_plan |
| plan_day | `plan_day` | `ada_daily_summary`, `ada_weekly_comparison` | merged | tools-merge-calendar-plan | tool_merge_calendar_plan |
| gev | `gev_command` | `gev_tour` | merged | tools-merge-gev | tool_merge_gev |
| devin | `devin` | `devin_dispatch`, `devin_followup`, `devin_answer` | merged | tools-merge-devin-mcp | tool_merge_devin |
| devin_read | `devin_read` | `devin_status`, `devin_jobs`, `devin_pending`, `devin_job_report`, `ada_devteam_review` | merged | tools-merge-devin-mcp | tool_merge_devin |
| cast_to_screen | `cast_to_screen` | `vcast_say`, `vcast_list`, `vcast_status`, `vcast_shortcut` | merged | tools-merge-display | tool_merge_display |
| vcast_snapshot | `vcast_snapshot` | `capture_frame` | merged | tools-merge-display | tool_merge_display |
| ha_search | `home_search` | `search_home_devices`, `list_home_devices`, `search_devices`, `search_sensors`, `list_sensors`, `ada_ha_search_devices`, `ada_ha_search_sensors`, `ada_ha_search_events` | merged | tools-merge-ha | tool_merge_ha |
| ha_state | `get_home_state` | `ada_ha_get_state` | merged | tools-merge-ha | tool_merge_ha |
| ha_history | `home_history` | `get_logbook`, `get_sensor_history`, `get_entity_events`, `get_recent_events`, `ada_ha_history` | merged | tools-merge-ha | tool_merge_ha |
| ha_control | `control_entity` | `control_cover`, `control_media_player`, `press_button` | merged | tools-merge-ha | tool_merge_ha |
| ha_confidence | `ha_confidence` | `ada_ha_get_device_confidence`, `ada_ha_set_device_confidence` | merged | tools-merge-ha | tool_merge_ha |
| docs | `docs` | `ada_doc_search`, `ada_doc_get`, `ada_doc_print`, `ada_doc_archive` | merged | tools-merge-docs-drive | tool_merge_docs_drive |
| drive | `drive` | `drive_search`, `drive_show`, `drive_get`, `drive_update` | merged | tools-merge-docs-drive | tool_merge_docs_drive |
| memory_search | `ada_memory_search` | `guest_recall` | merged | tools-merge-memory | tool_merge_memory |
| memory_remember | `ada_remember` | `vocab_note`, `report_habit_observation`, `guest_remember`, `guest_remember_private` | merged | tools-merge-memory | tool_merge_memory |
| memory_recall | `ada_session_recall` | `ada_ha_recall` | merged | tools-merge-memory | tool_merge_memory |
| meta_voice_persona | `ada_persona` | `ada_set_voice` | merged | tools-merge-meta-voice | tool_merge_meta_voice |
| meta_voice_ops | `ada_ops` | `ada_outcome`, `ada_usage_summary`, `ada_mddb_health`, `ada_decision_check`, `ada_deep_research`, `report_refresh` | merged | tools-merge-meta-voice | tool_merge_meta_voice |
| meta_voice_enroll | `ada_enroll_speaker` | `guest_register` | merged | tools-merge-meta-voice | tool_merge_meta_voice |
| tasks | `tasks` | `tasks_add`, `tasks_list`, `tasks_complete`, `tasks_move` | merged | tools-merge-tasks-status | tool_merge_tasks_status |
| home_status | `home_status` | `get_battery_status`, `get_battery_detail`, `get_power_summary`, `get_inverter_status`, `get_pool_status`, `get_dashboard_tab`, `get_habit_status` | merged | tools-merge-tasks-status | tool_merge_tasks_status |
| chat_send | `chat_send` | `photos_pick`, `photos_picked`, `sys_show_uploaded_document`, `process_document_upload`, `doc_upload_card_action` | merged | tools-merge-tasks-status | tool_merge_tasks_status |
| yt | `yt` | `yt_cast`, `yt_cast_status`, `yt_cast_stop`, `yt_transcript` | merged | tools-merge-yt | tool_merge_yt |
| kanban | `kanban` | `ada_board_write` | merged | ada-kanban-access | kanban_review |

## Absorbed-name surface (`_ALIASES`)

Retired decl names still routable — the model's stale call lands on the canonical tool.

| alias | routes to |
|---|---|
| `ada_board_write` | `kanban` |
| `ada_daily_summary` | `plan_day` |
| `ada_decision_check` | `ada_ops` |
| `ada_deep_research` | `ada_ops` |
| `ada_devteam_review` | `devin_read` |
| `ada_doc_archive` | `docs` |
| `ada_doc_get` | `docs` |
| `ada_doc_print` | `docs` |
| `ada_doc_search` | `docs` |
| `ada_ha_get_device_confidence` | `ha_confidence` |
| `ada_ha_get_state` | `get_home_state` |
| `ada_ha_history` | `home_history` |
| `ada_ha_recall` | `ada_session_recall` |
| `ada_ha_search_devices` | `home_search` |
| `ada_ha_search_events` | `home_search` |
| `ada_ha_search_sensors` | `home_search` |
| `ada_ha_set_device_confidence` | `ha_confidence` |
| `ada_mddb_health` | `ada_ops` |
| `ada_outcome` | `ada_ops` |
| `ada_set_voice` | `ada_persona` |
| `ada_usage_summary` | `ada_ops` |
| `ada_weekly_comparison` | `plan_day` |
| `calendar_create_event` | `calendar_write` |
| `calendar_delete_event` | `calendar_write` |
| `calendar_freebusy` | `calendar_read` |
| `calendar_list_calendars` | `calendar_read` |
| `calendar_list_events` | `calendar_read` |
| `calendar_shift_overdue` | `calendar_write` |
| `capture_frame` | `vcast_snapshot` |
| `cctv_snapshot` | `ada_camera_snapshot` |
| `cms_automation` | `cms_edit` |
| `cms_delete_page` | `cms_edit` |
| `cms_get_page` | `cms_read` |
| `cms_list_pages` | `cms_read` |
| `cms_note_update` | `cms_edit` |
| `cms_verify_page` | `cms_read` |
| `control_cover` | `control_entity` |
| `control_media_player` | `control_entity` |
| `devin_answer` | `devin` |
| `devin_dispatch` | `devin` |
| `devin_followup` | `devin` |
| `devin_job_report` | `devin_read` |
| `devin_jobs` | `devin_read` |
| `devin_pending` | `devin_read` |
| `devin_status` | `devin_read` |
| `doc_upload_card_action` | `chat_send` |
| `drive_get` | `drive` |
| `drive_search` | `drive` |
| `drive_show` | `drive` |
| `drive_update` | `drive` |
| `get_battery_detail` | `home_status` |
| `get_battery_status` | `home_status` |
| `get_dashboard_tab` | `home_status` |
| `get_entity_events` | `home_history` |
| `get_habit_status` | `home_status` |
| `get_inverter_status` | `home_status` |
| `get_logbook` | `home_history` |
| `get_pool_status` | `home_status` |
| `get_power_summary` | `home_status` |
| `get_recent_events` | `home_history` |
| `get_sensor_history` | `home_history` |
| `gev_tour` | `gev_command` |
| `guest_recall` | `ada_memory_search` |
| `guest_register` | `ada_enroll_speaker` |
| `guest_remember` | `ada_remember` |
| `guest_remember_private` | `ada_remember` |
| `list_home_devices` | `home_search` |
| `list_sensors` | `home_search` |
| `photos_pick` | `chat_send` |
| `photos_picked` | `chat_send` |
| `press_button` | `control_entity` |
| `process_document_upload` | `chat_send` |
| `report_habit_observation` | `ada_remember` |
| `report_refresh` | `ada_ops` |
| `search_devices` | `home_search` |
| `search_home_devices` | `home_search` |
| `search_sensors` | `home_search` |
| `sys_show_uploaded_document` | `chat_send` |
| `tasks_add` | `tasks` |
| `tasks_complete` | `tasks` |
| `tasks_list` | `tasks` |
| `tasks_move` | `tasks` |
| `traffic_camera` | `ada_camera_snapshot` |
| `vcast_list` | `cast_to_screen` |
| `vcast_say` | `cast_to_screen` |
| `vcast_shortcut` | `cast_to_screen` |
| `vcast_status` | `cast_to_screen` |
| `vocab_note` | `ada_remember` |
| `yt_cast` | `yt` |
| `yt_cast_status` | `yt` |
| `yt_cast_stop` | `yt` |
| `yt_transcript` | `yt` |

## Drift notes

- tools declared but missing an `ssot.tools.yml` registry row (0): none
- registry `ada-voice` surfaces not on the live surface (1): `host_status (staged drop integrations/ada-voice)`
- `coverage_debt` — declared tools with no scenario reference (31): `voice_fx`, `percussion`, `ada_device_acl`, `ada_resolve_action`, `chat_send`, `control_cover`, `devin_followup`, `devin_job_report`, `drive_update`, `get_battery_detail`, `get_battery_status`, `get_dashboard_tab`, `get_entity_events`, `get_habit_status`, `get_inverter_status`, `get_pool_status`, `get_power_summary`, `get_sensor_history`, `gev_tour`, `guest_register`, `photos_pick`, `photos_picked`, `press_button`, `tasks_move`, `yt_cast_status`, `place_report`, `cpt_post`, `weather_station`, `ada_sweep`, `ada_lesson`, `ada_adobe_stock`
- `tool_guide.yml` entries for undeclared tools: `ada_board_write`

<!-- /tools-commands:auto -->

*Sources: ada-voice `backend/realtime_provider.py`, `backend/tools.d/*` + `manifest.yml`, `backend/tool_guide.yml`, `tool_runner/common.py::_ALIASES`, `docs/ssot/ssot.tool-surface.yml`, `tests/scenarios-live/*` — joined with chaba `docs/ssot/infrastructure/ssot.tools.yml`. Last-changed = `git blame` span of each declaration.*
