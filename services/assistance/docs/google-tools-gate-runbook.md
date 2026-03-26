# Google Tools Gate — Enable/Disable Runbook

Operator runbook for safely enabling and disabling the Google MCP tool gates
in the `jarvis-backend` service.

---

## Table of Contents

1. [Background](#background)
2. [Gate keys reference](#gate-keys-reference)
3. [Preconditions](#preconditions)
4. [Enable checklist](#enable-checklist)
5. [Disable (rollback) checklist](#disable-rollback-checklist)
6. [Verification steps](#verification-steps)
7. [Partial enablement](#partial-enablement)
8. [Blast radius / safety](#blast-radius--safety)

---

## Background

`jarvis-backend` reads boolean feature-flag keys from a `sys_kv` store at
startup (or on each request, depending on implementation).  When a key is
absent or set to `false`, any MCP tool that belongs to that gate returns
`HTTP 403` with a structured error before touching any external Google API.

This runbook covers:
- Which keys exist and what they guard
- How to edit them and apply the change
- How to verify the gate is active or inactive

---

## Gate keys reference

| `sys_kv` key              | Tools gated                             | Default |
|---------------------------|-----------------------------------------|---------|
| `google.tools.enabled`    | Master switch — all Google tools        | `false` |
| `google.sheets.enabled`   | `google_sheets_*` tool group            | `false` |
| `google.calendar.enabled` | `google_calendar_*` tool group          | `false` |
| `google.tasks.enabled`    | `google_tasks_*` tool group             | `false` |
| `gmail.enabled`           | `gmail_*` tool group                    | `false` |

**Evaluation order:** A tool is accessible only when **both** the master switch
(`google.tools.enabled`) **and** the relevant per-service key are `true`.
Disabling the master switch is sufficient to block all Google tools regardless
of the per-service keys.

---

## Preconditions

Before enabling or disabling any gate:

1. **Locate the `sys_kv` configuration file.**
   The backing store is typically a JSON or YAML flat file referenced by the
   `SYS_KV_PATH` environment variable in the stack's `.env`:

   ```
   stacks/idc1-assistance/.env   →   SYS_KV_PATH=/data/sys_kv.json
   ```

   If `SYS_KV_PATH` is not set, the backend falls back to its compiled-in
   default path (check `jarvis-backend` source / container volume mounts).

2. **Confirm you have write access** to the `sys_kv` file on the host where
   `jarvis-backend` runs (typically `idc1`).

3. **No restart required** if `jarvis-backend` re-reads `sys_kv` on every
   request.  If it caches values at startup a container restart is needed —
   verify via the service's `/health` or `/config` endpoint after making
   changes.

4. **Notify relevant consumers** (Jarvis frontend, downstream agents) before
   toggling gates, as tool calls will begin failing or passing immediately.

5. **Backup the current `sys_kv` file** before any change:

   ```bash
   cp /data/sys_kv.json /data/sys_kv.json.bak-$(date +%Y%m%d-%H%M%S)
   ```

---

## Enable checklist

Use this checklist when turning Google tools **on**.

- [ ] **1. Review OAuth / credentials.**
  Confirm the service-account key or OAuth token for the relevant Google
  APIs is present and valid in the backend environment
  (`GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLIENT_ID`, etc.).

- [ ] **2. Verify scope coverage.**
  The credential must include the scopes for the tools you are enabling
  (e.g. `https://www.googleapis.com/auth/spreadsheets` for Sheets).

- [ ] **3. Backup `sys_kv`** (see Preconditions step 5).

- [ ] **4. Set master switch and the desired per-service keys.**

  Example — enable Sheets only:

  ```bash
  # Read → edit → write (jq example)
  jq '.["google.tools.enabled"] = true | .["google.sheets.enabled"] = true' \
      /data/sys_kv.json > /tmp/sys_kv_new.json \
      && mv /tmp/sys_kv_new.json /data/sys_kv.json
  ```

  Example — enable all Google tools:

  ```bash
  jq '
    .["google.tools.enabled"]    = true |
    .["google.sheets.enabled"]   = true |
    .["google.calendar.enabled"] = true |
    .["google.tasks.enabled"]    = true |
    .["gmail.enabled"]           = true
  ' /data/sys_kv.json > /tmp/sys_kv_new.json \
      && mv /tmp/sys_kv_new.json /data/sys_kv.json
  ```

- [ ] **5. Restart `jarvis-backend` if startup-cached** (see Preconditions step 3):

  ```bash
  cd stacks/idc1-assistance
  docker compose restart jarvis-backend
  ```

- [ ] **6. Verify gates are open** — see [Verification steps](#verification-steps).

- [ ] **7. Confirm no unexpected downstream errors** (check logs for 5xx from
  Google APIs; that would indicate credential / scope issues, not gate issues).

---

## Disable (rollback) checklist

Use this checklist when turning Google tools **off** or rolling back.

- [ ] **1. Backup `sys_kv`** (see Preconditions step 5).

- [ ] **2. Set master switch to `false`.**
  Disabling the master key blocks all tools immediately.

  ```bash
  jq '.["google.tools.enabled"] = false' \
      /data/sys_kv.json > /tmp/sys_kv_new.json \
      && mv /tmp/sys_kv_new.json /data/sys_kv.json
  ```

  To also disable individual keys (belt-and-suspenders):

  ```bash
  jq '
    .["google.tools.enabled"]    = false |
    .["google.sheets.enabled"]   = false |
    .["google.calendar.enabled"] = false |
    .["google.tasks.enabled"]    = false |
    .["gmail.enabled"]           = false
  ' /data/sys_kv.json > /tmp/sys_kv_new.json \
      && mv /tmp/sys_kv_new.json /data/sys_kv.json
  ```

- [ ] **3. Restart `jarvis-backend` if startup-cached.**

- [ ] **4. Verify gates are closed** — see [Verification steps](#verification-steps).

- [ ] **5. Notify consumers** that Google tool calls will now return `403`.

---

## Verification steps

### A — Verify a gate is **closed** (disabled)

Call any gated tool endpoint and expect `HTTP 403`.  The response body must
contain `google_tools_disabled` and the name of the missing/false key.

```bash
# Replace <HOST> and <PORT> with actual jarvis-backend address,
# and <TOOL> with a tool name guarded by the gate (e.g. google_sheets_read).

curl -s -o /tmp/gate_response.json -w "%{http_code}" \
  -X POST http://<HOST>:<PORT>/invoke \
  -H "Content-Type: application/json" \
  -d '{"tool": "<TOOL>", "arguments": {}}'
```

**Expected HTTP status:** `403`

**Expected JSON body shape:**

```json
{
  "error": "google_tools_disabled",
  "detail": "google_tools_disabled",
  "required_sys_kv_key": "google.tools.enabled"
}
```

Or, for a per-service key that is off while the master is on:

```json
{
  "error": "google_tools_disabled",
  "detail": "google_tools_disabled",
  "required_sys_kv_key": "google.sheets.enabled"
}
```

PowerShell equivalent:

```powershell
$r = Invoke-RestMethod -Method Post `
  -Uri "http://<HOST>:<PORT>/invoke" `
  -ContentType "application/json" `
  -Body '{"tool": "<TOOL>", "arguments": {}}' `
  -SkipHttpErrorCheck
$r | ConvertTo-Json
```

### B — Verify a gate is **open** (enabled)

The same call must **not** return `403` from the gate layer.  It may still
return an API-level error if credentials are misconfigured, but the gate itself
must not block it.

```bash
curl -s -X POST http://<HOST>:<PORT>/invoke \
  -H "Content-Type: application/json" \
  -d '{"tool": "<TOOL>", "arguments": {}}'
# Must NOT return {"error": "google_tools_disabled", ...}
```

### C — Health / config endpoint

If `jarvis-backend` exposes a `/health` or `/config` endpoint, confirm the
current state of the keys:

```bash
curl -s http://<HOST>:<PORT>/health | jq '.sys_kv'
# or
curl -s http://<HOST>:<PORT>/config | jq '.feature_flags'
```

---

## Partial enablement

You can enable individual Google services while leaving others gated.

**Example — Sheets only:**

```bash
jq '
  .["google.tools.enabled"]    = true  |
  .["google.sheets.enabled"]   = true  |
  .["google.calendar.enabled"] = false |
  .["google.tasks.enabled"]    = false |
  .["gmail.enabled"]           = false
' /data/sys_kv.json > /tmp/sys_kv_new.json \
    && mv /tmp/sys_kv_new.json /data/sys_kv.json
```

After applying, run verification probes against both an enabled tool
(`google_sheets_*`) and a disabled tool (`google_calendar_*`) to confirm
the expected responses.

---

## Blast radius / safety

### What breaks when Google tools are disabled

| Affected area                   | Impact                                                    |
|---------------------------------|-----------------------------------------------------------|
| Jarvis MCP tool calls           | Any `google_sheets_*`, `google_calendar_*`, `google_tasks_*`, or `gmail_*` tool returns `HTTP 403` immediately |
| Downstream agents / assistants  | Any workflow step that invokes a gated tool will fail at that step |
| Frontend UX                     | Tool-use actions visible to users will fail with an error response |

Disabling the gates does **not** affect:
- Non-Google MCP tools
- Jarvis frontend loading or navigation
- Backend `/health` endpoint
- Authentication / authorisation for non-Google tools

### What is safe to test without external side effects

- Calling a **disabled** gate endpoint: the backend short-circuits before
  contacting any Google API, so there are no external side effects and no
  quota consumption.
- Reading `sys_kv.json` or the `/health` endpoint.
- Editing `sys_kv.json` while `jarvis-backend` is stopped.

### Toggling in production

Prefer toggling one service at a time (e.g. Sheets before Calendar) and
verifying each change before proceeding to the next.  The master switch
(`google.tools.enabled = false`) is the fastest rollback path.
