---
description: Triage UI text-input Gemini Live failures (Jarvis)
---

# Goal
Collect the minimum evidence to diagnose UI text-input issues related to Gemini Live / WS (e.g. `gemini_live_model_not_found`, WS close 1008, no response).

# Preconditions
- You can open Jarvis UI in a browser.
- You have access to the Docker host running `idc1-assistance`.

# Step 1: Reproduce in UI (text input)
1. Open Jarvis UI:
   - `http://127.0.0.1:18080/jarvis/`
2. Click **Initialize**.
3. Send a short text message.

Record:

- UTC timestamp
- exact user input
- what the UI showed (error string / no response)

# Step 2: Capture frontend console + WS evidence
In browser DevTools:

- Console tab:
  - filter for: `ws`, `websocket`, `live`, `gemini`, `error`
  - copy/paste the relevant log block
- Network tab:
  - filter for `ws`
  - click the WebSocket request
  - copy:
    - close code / reason (if any)
    - last inbound/outbound frames around the failure

# Step 3: Backend logs (host)
Run on the Docker host:

```bash
docker logs --since 20m --tail 600 idc1-assistance-jarvis-backend-1 \
  | egrep -i 'gemini_live_|model_not_found|Requested entity was not found|ws|websocket|1007|1008|Traceback|Exception|ERROR' || true
```

# Step 4: Confirm effective model/env (host)
```bash
docker exec idc1-assistance-jarvis-backend-1 sh -lc 'env | egrep "^(GEMINI_LIVE_MODEL|GEMINI_API_KEY)=|^PORT=" || true' \
  | sed -E 's/(GEMINI_API_KEY)=.*/\1=<redacted>/'
```

# Step 5: Health + one golden-path API check (host)
```bash
curl -fsS http://127.0.0.1:18018/health
curl -fsS 'http://127.0.0.1:18018/reminders?status=pending&limit=3'
```

# Expected outputs to paste back
- Frontend console logs around the failure
- WS close code / reason
- Backend log grep output
- `GEMINI_LIVE_MODEL` value (and confirmation key is set, redacted)
- `/health` response
