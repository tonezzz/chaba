# Assistance Service — Tool Reference

Deterministic tools exposed by the assistance service.  
These tools are always available regardless of the active Gemini Live model state.

## Skills tools

### `system_skills_list`

Returns all skill rows currently loaded from the active Skills Sheet, with their resolved status.

**Request**
```json
{}
```

**Response**
```json
{
  "ok": true,
  "skills": [
    {
      "name": "weather_lookup",
      "enabled": true,
      "priority": 10,
      "match_type": "prefix",
      "pattern": "อากาศ",
      "lang": "th",
      "handler": "tool_call",
      "arg_json": { "tool": "get_weather", "args": {} }
    },
    {
      "name": "live_api_best_prac",
      "enabled": true,
      "priority": 50,
      "match_type": "none",
      "pattern": "",
      "lang": "",
      "handler": "inject",
      "arg_json": {}
    }
  ],
  "routing_enabled": true,
  "sheet_name": "jarvis-skills-prod"
}
```

**Use case:** Verify which skills are active after a sheet update or reload.  
See [ACTION.md — Verify](ACTION.md#verify).

---

### `system_skill_get`

Fetches a single skill row by name.

**Request**
```json
{ "name": "weather_lookup" }
```

**Response**
```json
{
  "ok": true,
  "skill": {
    "name": "weather_lookup",
    "enabled": true,
    "priority": 10,
    "match_type": "prefix",
    "pattern": "อากาศ",
    "lang": "th",
    "handler": "tool_call",
    "arg_json": { "tool": "get_weather", "args": {} }
  }
}
```

**Error response (not found)**
```json
{ "ok": false, "error": "skill not found", "name": "weather_lookup" }
```

---

## System tools

### `system_macros_list`

Returns all loaded macro rows with their enabled state.

**Request**
```json
{}
```

**Response**
```json
{
  "ok": true,
  "macros": [
    { "name": "macro_what_time", "enabled": true }
  ]
}
```

---

### `system_run_macro`

Executes a named macro.

**Request**
```json
{ "name": "macro_what_time", "args": {} }
```

**Response**
```json
{ "ok": true, "result": "..." }
```

---

### `time_now`

Returns the current server time and the active instance identifier.

**Request**
```json
{}
```

**Response**
```json
{ "ok": true, "time": "2026-03-27T05:00:00Z", "instance_id": "jarvis-prod-01" }
```

---

## Tool invocation patterns

Tools can be invoked in three ways:

| Method | Example |
|--------|---------|
| Direct WS message | `/tool system_skills_list {}` |
| Gemini model tool call | Model emits a `functionCall` that the dispatcher resolves |
| HTTP (debug only; deployment-specific) | If enabled in your environment, use the documented admin/debug HTTP endpoint for tool invocation |

---

## Related

- [SYSTEM.md](SYSTEM.md) — Skills Sheet schema and sys_kv keys
- [OVERVIEW.md](OVERVIEW.md) — Routing architecture diagram
- [ACTION.md](ACTION.md) — Operator procedures (update → reload → verify)
