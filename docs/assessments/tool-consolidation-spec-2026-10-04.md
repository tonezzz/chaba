# Tool Consolidation Spec — 2026-10-04

**Input:** tool-surface-2026-10-04.md (103 declared, ~55–65 target).
**Rule set:** same-target tools merge via `action=`/`mode=`; old names stay
registered as hidden aliases one release; zero-use tools go to `retire`
candidates only after the 30d window confirms — guest_* and calendar-writes
get an explicit probe first.

## Merge groups → target surface

### memory (8 → 4)

| keep | absorbs | shape |
|---|---|---|
| `ada_memory_search` | `guest_recall` | `search(q, scope=all|banks|sessions|guest)` |
| `ada_remember` | `vocab_note`, `report_habit_observation`, `guest_remember`, `guest_remember_private` | `remember(text, kind=fact|vocab|habit|guest, private=false)` |
| `ada_forget` | — | unchanged |
| `ada_session_recall` | `ada_ha_recall` | `recall(question, scope=sessions|history)` |

`ada_resolve_action` stays separate (workflow tool, not memory).

### display (8 → 2)

| keep | absorbs | shape |
|---|---|---|
| `cast_to_screen` | `vcast_say`, `vcast_list`, `vcast_status`, `vcast_shortcut` | `cast_to_screen(action=cast|say|list|status|shortcut, ...)` |
| `vcast_snapshot` | `capture_frame` | unchanged — verification loop needs it separate |
| `vcast_gesture` | — | unchanged (distinct subsystem) |

### camera (5 → 2)

| keep | absorbs | shape |
|---|---|---|
| `ada_camera_snapshot` | `cctv_snapshot`, `traffic_camera` | `camera_snapshot(source=auto|vms|traffic, view=..., screen=N)` |
| `cctv_wall` | — | unchanged (wall ≠ single frame) |

`vcast_snapshot` keeps display capture; `capture_frame` retires into it.

### cms (7 → 3)

| keep | absorbs | shape |
|---|---|---|
| `cms_publish_page` | — | unchanged (the big writer) |
| `cms_read` *(new)* | `cms_get_page`, `cms_list_pages`, `cms_verify_page` | `cms_read(action=get|list|verify, key=...)` |
| `cms_edit` *(new)* | `cms_note_update`, `cms_delete_page`, `cms_automation` | `cms_edit(action=note|delete|automate, ...)` |

### ha (14 → 6)

| keep | absorbs | shape |
|---|---|---|
| `home_search` *(new)* | `search_home_devices`, `list_home_devices`, `search_sensors`, `list_sensors`, `ada_ha_search_devices`, `ada_ha_search_sensors`, `ada_ha_search_events`, `search_devices` | `home_search(q, kind=device|sensor|event)` |
| `get_home_state` | `ada_ha_get_state` | `state(entity? domain?)` |
| `home_history` *(new)* | `get_logbook`, `get_sensor_history`, `get_entity_events`, `ada_ha_history`, `get_recent_events` | `home_history(entity|domain, window)` |
| `control_entity` | `control_cover`, `control_media_player`, `press_button`, `media_player_*` | `control(entity, action=..., ...)` — domain dispatch inside |
| `tv_action` | — | kept separate (complex param surface) |
| `ha_confidence` *(new)* | `ada_ha_get_device_confidence`, `ada_ha_set_device_confidence` | `ha_confidence(entity, set?)` |

### calendar+plan (9 → 3)

| keep | absorbs | shape |
|---|---|---|
| `calendar_read` *(new)* | `calendar_list_events`, `calendar_list_calendars`, `calendar_freebusy` | `cal(action=events|calendars|freebusy)` |
| `calendar_write` *(new)* | `calendar_create_event`, `calendar_delete_event`, `calendar_shift_overdue` | `cal(action=create|delete|shift, ...)` — gate writes |
| `plan_day` | `ada_daily_summary`, `ada_weekly_comparison` | `plan_day(period=today|tomorrow|week)` |

### docs+drive (8 → 2)

| keep | absorbs | shape |
|---|---|---|
| `docs` *(new)* | `ada_doc_search`, `ada_doc_get`, `ada_doc_print`, `ada_doc_archive` | `docs(action=search|get|print|archive)` |
| `drive` *(new)* | `drive_search`, `drive_show`, `drive_get`, `drive_update` | `drive(action=search|show|get|update)` |

### tasks+status (10 → 3)

| keep | absorbs | shape |
|---|---|---|
| `tasks` *(new)* | `tasks_add`, `tasks_list`, `tasks_complete`, `tasks_move` | `tasks(action=add|list|done|move)` |
| `home_status` *(new)* | `get_battery_status`, `get_battery_detail`, `get_power_summary`, `get_inverter_status`, `get_pool_status`, `get_dashboard_tab`, `get_habit_status` | `status(what=battery|power|inverter|pool|dashboard|habit)` |
| `chat_send` | `photos_pick`, `photos_picked`, `sys_show_uploaded_document`, `process_document_upload`, `doc_upload_card_action` | `chat_send(channel, text|photo|doc)` |

### devin (8 → 2)

| keep | absorbs | shape |
|---|---|---|
| `devin_dispatch` | `devin_followup`, `devin_answer` | `devin(action=dispatch|followup|answer, task_id?)` |
| `devin_read` *(new)* | `devin_status`, `devin_jobs`, `devin_pending`, `devin_job_report`, `ada_devteam_review` | `devin(action=status|jobs|pending|report)` |

### yt (4 → 1)

`yt_cast` absorbs `yt_cast_status`, `yt_cast_stop`, `yt_transcript` —
`yt(action=cast|status|stop|transcript)`.

### gev (2 → 1)

`gev_command` absorbs `gev_tour` — `gev(command|tour=...)`.

### meta/voice (8 → 3)

| keep | absorbs | shape |
|---|---|---|
| `ada_persona` | `ada_set_voice` | `persona(set_voice?...)` |
| `ada_ops` *(new)* | `ada_outcome`, `ada_usage_summary`, `ada_mddb_health`, `ada_decision_check`, `ada_deep_research` | `ops(action=outcome|usage|health|check|research)` |
| `ada_enroll_speaker` | `guest_register` | `enroll(who=speaker|guest)` |

### untouched

`web_search` (singular, fine), `set_facial_expression` (UI auto), `tv_action`.

## Result

~**38 voice-facing tools** (from 103) + aliases. MCP-side duplicates
(mcp-health/mcp-debug, ha/michael-ha/michael-dev servers) handled separately
in `tools-merge-devin-mcp` — that card audits which Devin-side MCP servers are
still needed after the consolidations above.

## Migration / aliases

Each merged parent keeps the absorbed names registered but hidden (`x-legacy:
true`); alias → parent dispatch table lives in `tool_runner._ALIASES`.
Remove aliases after the regression card goes green on two consecutive
benchmarks.

## Gates preserved

- `DEVIN_CONFIRMED_TOOLS` and `confirm_strip` logic unchanged — the confirm
  gate keys off resolved tool name, not alias.
- `ada_camera_snapshot` live-freshness behaviour unchanged (`mode=direct`
  proposals still pending from earlier session).
