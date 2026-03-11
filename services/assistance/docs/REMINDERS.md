
 # Reminders (Overview)
 
 This document explains how reminders work end-to-end in the `idc1-assistance` stack.
 
 ## What a reminder is
 
 A reminder is a memory item with:
 - **`kind=reminder`**
 - **`status`**:
   - `pending` (active)
   - `done` (completed)
 - **time fields** (unix timestamps in UTC):
   - `due_at` (the user-intended deadline)
   - `notify_at` (when Jarvis should notify)
   - `hide_until` (optional; temporarily hides the reminder from default lists)
 
 ## Data flow and storage (authoritative vs cache)
 
 - **Weaviate** is the **authoritative** memory store (cross-session consistency).
 - **SQLite (`jarvis_sessions.sqlite`)** is a **local scheduler cache** used for:
   - fast listing
   - local due checks
   - recovery when Weaviate is temporarily unavailable

 ## Weaviate reminder persistence

 Reminders are written to **SQLite first** (reliability + local scheduler), then (when enabled) written-through to **Weaviate** for cross-device consistency.

 - **Enable Weaviate**:
   - Set `WEAVIATE_URL` (stack default is typically `http://weaviate:8080`).
 - **Disable Weaviate (SQLite-only)**:
   - Unset `WEAVIATE_URL` or set it to an empty string.

 Behavior:
 - **Write-through**: if `WEAVIATE_URL` is set, create/update/done operations attempt a Weaviate upsert/update.
 - **Authoritative reads**: when `WEAVIATE_URL` is set, list endpoints prefer Weaviate reads (with SQLite fallback on error).
 - **Scheduler**: the reminder scheduler loop uses SQLite as its local due-check cache.

 Verification:
 - Create a reminder, then `GET /reminders?status=pending` should report `"source": "weaviate"` when Weaviate reads succeed.
 - If Weaviate is down, the same request should fall back to `"source": "sqlite_fallback"` and still return reminders.
 
 ```mermaid
 flowchart LR
   U[User] <-->|Chat / voice| FE[Jarvis Frontend]
   FE -->|WS /ws/live| BE[Jarvis Backend]
 
   BE -->|create/list/update| DB[(jarvis_sessions.sqlite)]
   BE -->|upsert/read| WV[Weaviate :8080]
 
   DB -->|due reminders| BE
   BE -->|WS event: reminder_*| FE
 
   subgraph Reminder lifecycle
     P[pending] -->|done| D[done]
     P -->|later: hide_until| H[hidden]
     H -->|time passes| P
     P -->|reschedule: notify_at| P
   end
 ```
 
 ## How reminders are created
 
 There are two main creation paths:
 - **Deterministic WS sub-agent**: `reminder-setup`
   - Example: `reminder setup: remind me tomorrow at 9:00am to do job1`
 - **Gemini Live tool calls** (model calls backend tools)
   - For listing/updating reminders, the model can call:
     - `reminders_list`
     - `reminders_upcoming`
     - `reminders_done`
 
 Creation should write to SQLite first (reliability) and then write-through to Weaviate.
 
 ## Common operations
 
 - **List reminders**
   - Default behavior typically excludes hidden items (those with `hide_until` in the future).
 - **Done**
   - Marks a reminder completed so it stops showing in “today” and “upcoming”.
 - **Later**
   - Sets `hide_until` to temporarily hide a reminder.
 - **Reschedule**
   - Updates `notify_at` (and typically clears `hide_until`).
 
 ## Backend HTTP endpoints
 
 - `GET /reminders`
 - `GET /reminders/upcoming`
 - `POST /reminders/{reminder_id}/done`
 - `POST /reminders/{reminder_id}/later?days=1`
 - `GET /reminders/{reminder_id}/reschedule/suggest`
 - `POST /reminders/{reminder_id}/reschedule?notify_at=<unix_ts>`
 
 ## WebSocket quick commands
 
 - `reminder setup: <text>`
 - `reminder add: <text>`
 - `reminder list pending`
 - `reminder done: <reminder_id>`
 - `reminder later: <reminder_id> 1`
 - `reminder reschedule: <reminder_id> tomorrow 09:00`
 - `reminder delete: <reminder_id>`

