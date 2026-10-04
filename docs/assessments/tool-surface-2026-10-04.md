# Tool Surface Census — 2026-10-04

**Source:** `ada-pi/backend/realtime_provider.py` tool declarations (103)
+ 7-day `function_call` journal on idc01 (ada-ha-tony) + ops-event tool hits.
**Purpose:** feed `tool-consolidation-design` — find overlaps, dead surface,
and merge groups based on real usage, not guesses.

## Headline numbers

- **103 declared tools** — the model sees all of them every session
- **~17 tools: zero calls in 7 days**
- **Top 10 tools carry ~85% of all calls**
- `set_facial_expression` alone is 16,703 calls (43% — auto-emitted, not user intent)

## Usage tiers

### Tier 1 — workhorses (>500 calls/7d)

| calls | tool | domain |
|---|---|---|
| 16703 | set_facial_expression | ui-auto |
| 3921 | ada_memory_search | memory |
| 1467 | cms_publish_page | cms |
| 981 | cast_to_screen | display |
| 933 | web_search | knowledge |
| 675 | ada_session_recall | memory |
| 619 | gev_command | gev |
| 609 | ada_remember | memory |
| 596 | cms_get_page | cms |
| 526 | cctv_wall | camera |
| 515 | vcast_say | display |

### Tier 2 — regulars (100–500)

cast/vision: `vcast_list` 446, `vcast_snapshot` 271, `ada_camera_snapshot` 210,
`cctv_snapshot` 166, `traffic_camera` 161 — cms: `cms_verify_page` 246,
`cms_list_pages` 122 — memory/docs: `ada_doc_search` 372, `ada_doc_get` 129,
`ada_persona` 132, `ada_resolve_action` 134, `ada_enroll_speaker` 125 —
HA: `search_home_devices` 316, `list_sensors` 245, `get_home_state` 204,
`search_sensors` 194, `list_home_devices` 180, `tv_action` 310,
`control_media_player` 115, `get_logbook` 103 — devin: `devin_jobs` 85,
`devin_dispatch` 76, `devin_status` 69 — drive: `drive_search` 134,
`drive_show` 115 — misc: `tasks_add` 168, `vocab_note` 95, `web_search`…

### Tier 3 — occasional (10–99)

tasks_list 28, yt_cast 60, yt_cast_status 53, yt_cast_stop 24, plan_day 45,
cms_note_update 44, get_dashboard_tab 40, cms_automation 40, vcast_gesture 22,
ada_ha_recall 21, ada_forget 21, yt_transcript 19, tasks_complete 19,
cms_delete_page 19, devin_answer 18, ada_usage_summary 16, devin_pending 15,
ada_doc_archive 12, ada_ha_search_sensors 10.

### Tier 4 — near-dead (1–9)

get_pool_status 8, tasks_move 7, get_sensor_history 7, get_power_summary 7,
chat_send 7, ada_ha_search_devices 7, press_button 6, devin_followup 6,
ada_devteam_review 6, devin_job_report 5, control_cover 5, ada_set_voice 5,
ada_mddb_health 5, ada_ha_search_events 5, gev_tour 4, ada_outcome 4,
ada_ha_get_device_confidence 4, get_inverter_status 3,
calendar_shift_overdue 3, ada_ha_history 3, ada_deep_research 3,
vcast_status 2, photos_pick 2, get_entity_events 2, calendar_freebusy 2,
ada_daily_summary 2, vcast_shortcut 1, media_player_* ~3…

### Tier 5 — ZERO calls in 7 days

`ada_decision_check`, `ada_doc_print`, `ada_ha_set_device_confidence`,
`ada_weekly_comparison`, `calendar_create_event`, `calendar_delete_event`,
`capture_frame`, `drive_get`, `drive_update`, `get_battery_detail`,
`get_habit_status`, `guest_recall`, `guest_register`, `guest_remember`,
`guest_remember_private`, `photos_picked`, `report_habit_observation`

## Overlap / merge candidates (design input)

- **memory**: `ada_memory_search` + `ada_session_recall` + `ada_ha_recall`
  + `guest_recall` — 4 retrieval paths, one could take `scope=` param
- **memory-write**: `ada_remember` + `vocab_note` + `report_habit_observation`
  + `guest_remember`(+_private) — all "save a fact" variants
- **display**: `cast_to_screen` + `vcast_say` + `vcast_list` + `vcast_snapshot`
  + `vcast_status` + `vcast_gesture` + `vcast_shortcut` — vcast_* could be
  `action=` on one display tool
- **camera**: `ada_camera_snapshot` + `cctv_snapshot` + `cctv_wall`
  + `traffic_camera` + `capture_frame` — 5 tools, one `mode=` split
- **cms**: `cms_publish_page` + `cms_get_page` + `cms_list_pages`
  + `cms_verify_page` + `cms_delete_page` + `cms_note_update`
  + `cms_automation` — standard CRUD suite, fine as-is OR one tool
- **docs**: `ada_doc_search` + `ada_doc_get` + `ada_doc_print`
  + `ada_doc_archive` + `drive_search` + `drive_show` + `drive_get`
  + `drive_update` — two parallel doc systems (mddb docs vs drive)
- **ha-search**: `search_home_devices` + `list_home_devices`
  + `search_sensors` + `list_sensors` + `get_home_state`
  + `ada_ha_search_devices` + `ada_ha_search_sensors`
  + `ada_ha_search_events` — THREE generations of the same search
- **ha-control**: `control_entity` + `control_cover` + `control_media_player`
  + `tv_action` + `press_button` — could unify under domain= param
- **devin**: `devin_dispatch` + `devin_status` + `devin_jobs` + `devin_pending`
  + `devin_followup` + `devin_answer` + `devin_job_report` + `ada_devteam_review`
  — 8 tools; dispatch+followup+answer is one conversation lifecycle
- **calendar**: `calendar_list_events` + `calendar_list_calendars`
  + `calendar_freebusy` + `calendar_create_event` + `calendar_delete_event`
  + `calendar_shift_overdue` + `plan_day` + `ada_daily_summary`
  + `ada_weekly_comparison` — read/write split; write tools unused
- **yt**: `yt_cast` + `yt_cast_status` + `yt_cast_stop` + `yt_transcript`
  — already action-family shaped
- **battery/energy**: `get_battery_detail` + `get_power_summary`
  + `get_inverter_status` + `get_pool_status` — sensor-status grab-bag
- **guest**: `guest_register` + `guest_recall` + `guest_remember`
  + `guest_remember_private` — all zero/near-zero use; keep or cut
- **ada-meta**: `ada_persona` + `ada_set_voice` + `ada_outcome`
  + `ada_usage_summary` + `ada_devteam_review` + `ada_decision_check`
  + `ada_deep_research` + `ada_mddb_health` — meta/research family

## Devin-side tool surface (for the same treatment)

- MCP servers: ~18 configured (mddb, yomi, github, postgres, mcp-health,
  mcp-llama, playlive, workflows, alphavantage, colab-mcp, mcp-focus,
  mcp-weaviate, docs, notebooklm, mcp-gpu, michael-ha, icloud, chrome-devtools,
  google-home-lan, home-assistant, michael-dev, docs-trade, mcp-debug, yomi…)
  — overlaps: mcp-health vs mcp-debug vs health-check skill; home-assistant
  vs michael-ha vs michael-dev vs google-home-lan; mddb vs mcp-weaviate
- Built-in: todo_write, code_search, subagents — fine

## First-cut recommendations for the design card

1. **Target surface ≈ 55–65 tools** — merge the overlap families above via
   `action=`/`mode=` params, keep old names as hidden aliases for one release
2. **Retire or hide** the 17 zero-use tools (verify 30d data first —
   guest_* may be rare-but-essential; calendar writes may be broken, not unused)
3. **Split `set_facial_expression` out of the tool count** — it's a UI event,
   not a user-facing tool; counting it skews the surface
4. **3rd-gen HA search tools** (`ada_ha_search_*` vs `search_*` vs
   `list_*`) is the worst duplication — pick one generation
5. Calendar write tools at zero calls → investigate whether they're broken
   (never invoked) before deciding retire vs fix

## Caveats

- Journal `name=` extraction includes a few model typo'd names
  (`ser_facial_expression`, `get_ashboard_tab`, `c_c_t_v_wall`) — noise,
  excluded from counts
- 7d window: seasonal tools (flood/weather spikes) under-represented
- Ops-event count (separate metric) shows the same top-20 shape — consistent
