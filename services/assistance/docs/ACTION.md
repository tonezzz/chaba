# Assistance Service — Operator Actions

Step-by-step procedures for managing Skills Sheet routing.  
For background and schema, see [SYSTEM.md](SYSTEM.md).

---

## Prerequisites

- Access to the Skills Sheet (identified by `system.skills.sheet_name` in `sys_kv`)
- Operator access to the Jarvis admin UI or API

---

## Update the Skills Sheet

1. Open the Skills Sheet identified by the current value of `system.skills.sheet_name`.
2. Edit or add rows following the schema in [SYSTEM.md — Skill row schema](SYSTEM.md#skill-row-schema).
3. Key rules:
   - `name` must be unique across all rows.
   - Set `enabled = false` to disable a row without deleting it.
   - Set `match_type = none` for inject-only rows (they have no runtime pattern).
   - `arg_json` must be valid JSON or left blank.

---

## Apply: System Reload

After saving sheet changes, trigger a reload so the backend picks them up:

**Option A — UI**
1. Navigate to **Settings → System → Reload**.
2. Confirm the reload prompt.
3. Wait for the success toast / status indicator.

**Option B — API (deployment-specific)**

If your deployment exposes an admin HTTP API for reload, use the endpoint documented for that environment.
The exact path and port can vary by stack; prefer the admin UI above when available.

> A reload does **not** restart the WebSocket session; active clients reconnect automatically.

---

## Verify

### 1. List loaded skills

```
/tool system_skills_list {}
```

Check the response:
- `ok` is `true`
- `sheet_name` matches `system.skills.sheet_name`
- `routing_enabled` matches `system.skills.routing.enabled`
- Expected rows appear in the `skills` array with correct `enabled` values

See [TOOLS.md — system_skills_list](TOOLS.md#system_skills_list) for the full response shape.

### 2. Fetch a specific skill

```
/tool system_skill_get { "name": "<skill-name>" }
```

Confirm the row fields match what was saved in the sheet.

### 3. Check the compat voice-commands endpoint

```bash
curl http://127.0.0.1:18018/config/voice_commands
```

The response is a backward-compatible representation derived from skill rows with a non-`none` `match_type`.  
Use this to confirm routing patterns are visible to older clients.

---

## Enable / Disable Sheet-First Routing

| Goal | Action |
|------|--------|
| Enable sheet-first routing | Set `system.skills.routing.enabled = true` in `sys_kv`, then reload |
| Disable (legacy fallback) | Set `system.skills.routing.enabled = false` in `sys_kv`, then reload |
| Change the active sheet | Update `system.skills.sheet_name` in `sys_kv`, then reload |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `system_skills_list` returns empty `skills` | `sheet_name` not set or sheet unreachable | Check `system.skills.sheet_name` in `sys_kv`; confirm sheet exists |
| Routing not triggering despite `routing_enabled: true` | Pattern mismatch | Check `match_type` and `pattern`; test with `exact` before switching to `regex` |
| `routing_enabled` is `false` | Key not set or explicitly disabled | Set `system.skills.routing.enabled = true` and reload |
| `/config/voice_commands` returns empty list | No rows with non-`none` `match_type` are enabled | Enable at least one routing row in the sheet |
| Reload returns non-`ok` | Backend error loading sheet | Check backend logs; verify sheet format and `sheet_name` value |
