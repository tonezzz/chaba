# Test info

Operator SSOT:

- `services/assistance/docs/ACTION.md`

API SSOT:

- Prefer the live backend OpenAPI: `GET /openapi.json`

## Context

This file is a scratchpad for validating the GitHub Actions watcher integration in Jarvis.

Core goal:

- The watcher should only trigger when explicitly invoked (voice command / explicit REST call), not continuously.
- When a workflow run is detected and later completes, Jarvis should:
  - Broadcast events to connected Jarvis UI WebSockets.
  - Persist a minimal audit trail in the UI daily log (JSONL) so events are visible even if no WebSocket was connected.

Relevant backend pieces:

- **Watcher loop**: `services/assistance/jarvis-backend/main.py::_github_watch_loop`
- **Broadcast**: `main.py::_broadcast_to_user` (WebSocket only)
- **Persisted UI log**: `main.py::_append_ui_log_entries` and endpoint `GET /jarvis/api/logs/ui/today`

Event kinds written to UI log:

- `run_detected`
- `run_completed`
- `watch_error`

## Diagram

```mermaid
sequenceDiagram
  autonumber
  actor User
  participant UI as Jarvis UI (WebSocket)
  participant BE as Jarvis Backend
  participant GH as GitHub API
  participant LOG as UI Log (daily JSONL)

  Note over User,BE: Trigger (explicit only)
  alt Voice command phrase matched
    User->>UI: Speak trigger phrase
    UI->>BE: STT text over WebSocket
    BE->>BE: _handle_github_watch_voice()
    BE->>BE: github_actions_watch(...)
  else REST
    User->>BE: POST /jarvis/api/github/actions/watch/start
    BE->>BE: asyncio.create_task(_github_watch_loop)
  end

  loop poll every N seconds
    BE->>GH: GET /repos/{owner}/{repo}/actions/runs?per_page=1&branch=&event=
    GH-->>BE: latest workflow run
    alt new run_id detected
      BE->>LOG: append {type:github_actions, kind:run_detected, run:...}
      BE->>UI: send_json {type:github_actions, kind:run_detected, run:...}
      BE->>UI: send_json {type:text, text:"CI started: ..."}
    end
    alt status completed (and conclusion changed)
      BE->>LOG: append {type:github_actions, kind:run_completed, run:...}
      BE->>UI: send_json {type:github_actions, kind:run_completed, run:...}
      BE->>UI: send_json {type:text, text:"CI completed: ..."}
    end
  end

  opt error calling GitHub / token missing
    BE->>LOG: append {type:github_actions, kind:watch_error, error:"..."}
    BE->>UI: send_json {type:text, text:"GitHub Actions watch error: ..."}
  end
```

## Quick checks

- **Watcher running**: `GET /jarvis/api/github/actions/watch/list`
- **Latest run**: `GET /jarvis/api/github/actions/latest`
- **Persisted events**: `GET /jarvis/api/logs/ui/today` then search for `"type": "github_actions"`