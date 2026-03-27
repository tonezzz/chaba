# Assistance Service — System Configuration

Reference for Skills Sheet schema, `sys_kv` keys, and routing configuration.

## Skills Sheet

The Skills Sheet is the **single source of truth (SSOT)** for both skill routing and system-instruction injection.  
The sheet to load is identified by the `system.skills.sheet_name` key in `sys_kv`.

### Skill row schema

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `name` | string | ✓ | Unique identifier for the skill (e.g. `weather_lookup`) |
| `enabled` | boolean | ✓ | `true` to activate this row; `false` to skip silently |
| `priority` | integer | ✓ | Lower number = higher priority; used for tie-breaking and injection order |
| `match_type` | enum | — | How `pattern` is evaluated: `exact`, `prefix`, `regex`, or `none` (inject-only) |
| `pattern` | string | — | Transcript pattern to match against (interpreted per `match_type`) |
| `lang` | string | — | BCP-47 language tag for pattern matching (e.g. `th`, `en`); leave blank to match any |
| `handler` | enum | ✓ | What to do on match: `tool_call`, `inject`, or `passthrough` |
| `arg_json` | JSON string | — | Arguments forwarded to the handler (for `tool_call` rows: the tool name and fixed args) |

#### `handler` values

| Value | Behaviour |
|-------|-----------|
| `tool_call` | Executes the tool named in `arg_json.tool` with `arg_json.args` merged with any runtime args |
| `inject` | Folds the skill content into the system instruction at session start (routing not triggered at runtime) |
| `passthrough` | Matches but forwards the transcript to Gemini Live unchanged (useful for tagging without acting) |

#### `match_type` values

| Value | Behaviour |
|-------|-----------|
| `exact` | Case-folded exact string match |
| `prefix` | Transcript starts with `pattern` (after trimming) |
| `regex` | Full ECMAScript regex match against the transcript |
| `none` | Row is never matched at runtime (inject-only rows use this) |

### Example rows

```
name                  enabled  priority  match_type  pattern         lang  handler    arg_json
--------------------  -------  --------  ----------  --------------- ----  ---------  -----------------------------------------
weather_lookup        true     10        prefix      อากาศ           th    tool_call  {"tool":"get_weather","args":{}}
time_now              true     10        exact       what time is it  en   tool_call  {"tool":"time_now","args":{}}
live_api_best_prac    true     50        none                               inject     {}
```

---

## sys_kv Keys

`sys_kv` is the key-value store used to configure runtime behaviour without redeploy.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `system.skills.sheet_name` | string | _(none)_ | Name / ID of the Skills Sheet to load. Required for routing and injection to be active |
| `system.skills.routing.enabled` | boolean | `false` | Set to `true` to enable sheet-first routing. When `false`, all transcripts go directly to Gemini Live (legacy behaviour) |

### Setting a key

Use the operator UI or equivalent API:

```
POST /sys_kv/set
{ "key": "system.skills.routing.enabled", "value": true }
```

---

## Routing Behaviour Reference

| `routing.enabled` | `sheet_name` set | Effect |
|-------------------|-----------------|--------|
| `false` | any | Legacy mode — all transcripts sent to Gemini Live |
| `true` | _(none)_ | Routing enabled but no sheet loaded — falls through to Gemini Live |
| `true` | set | **Sheet-first routing active** — matched rows dispatched, unmatched fall through to Gemini Live |

---

## Compat: `/config/voice_commands`

`GET /config/voice_commands` returns a backward-compatible representation of routing rows for clients that pre-date the Skills Sheet.  
The skills sheet is the authoritative source; this endpoint derives its output from enabled rows with a non-`none` `match_type`.

---

For the full operator procedure see [ACTION.md](ACTION.md).
