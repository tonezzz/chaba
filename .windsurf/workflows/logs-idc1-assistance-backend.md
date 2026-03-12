---
description: Fetch idc1-assistance backend logs (Portainer-first)
---

# Goal
Get recent `jarvis-backend` logs quickly for debugging (5xx, reminders, Weaviate, Gemini Live).

# Preconditions
- Portainer is reachable for the target host.
- Stack name is `idc1-assistance`.

# Option A (preferred): Portainer UI
1. Open **Portainer**.
2. Go to **Containers**.
3. Select container (name may vary):
   - `idc1-assistance-jarvis-backend-1`
4. Open **Logs**.
5. Set tail to `200` or `1000` lines.

Suggested filters (manual scan):
- `weaviate`
- `reminder`
- `Traceback`
- `Exception`
- `502`
- `timeout`

# Option B (host CLI): tail + grep
Run on the host:

```bash
docker logs --since 30m --tail 600 idc1-assistance-jarvis-backend-1 | egrep -i 'weaviate|reminder|502|timeout|traceback|exception|error=' || true
```

# What “good” looks like
- No repeated connection failures to `http://weaviate:8080`.
- Reminder endpoints return `200` and log a clear source of reads (Weaviate vs fallback).
