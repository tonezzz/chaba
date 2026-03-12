---
description: Triage reminders + Weaviate issues (fast checklist)
---

# Goal
Determine whether reminder failures are caused by:
- Weaviate being down/unready
- networking/DNS issues inside the stack
- schema/object issues
- embedding provider failures causing write-through to fail
- backend falling back to SQLite unexpectedly

# Step 0: Establish reproduction
Pick one:
- UI / WS: `reminder add: <text>` then `reminder list pending`
- HTTP: `POST /reminders` then `GET /reminders?status=pending`

Record:
- timestamp of attempt
- expected reminder text

# Step 1: Check Weaviate readiness (Portainer UI)
1. Open container: `idc1-assistance-weaviate-1`.
2. Check logs for:
   - readiness loops
   - OOM / restarts
   - disk warnings

# Step 2: Check backend logs around the attempt
Use workflow: `logs-idc1-assistance-backend`.

Look for:
- request logs for `/reminders`
- `weaviate` errors (timeouts, 502, connection refused)
- schema bootstrap messages

# Step 3: Confirm Weaviate is reachable from backend network
Option A (Portainer UI): Exec into backend container
- `curl -sS -o /dev/null -w "%{http_code}\n" http://weaviate:8080/v1/.well-known/ready`

Expected:
- `200`

# Step 4: Confirm schema exists
From inside backend container:

```bash
curl -sS http://weaviate:8080/v1/schema/JarvisMemoryItem | head
```

# Step 5: Interpret outcomes
- If Weaviate readiness fails:
  - fix Weaviate first (resources, disk, crash loops).
- If readiness OK but schema missing:
  - backend bootstrap not running or failing.
- If schema OK but reminders missing:
  - likely write-through failure, wrong filters, or read source not Weaviate.

# Exit criteria
You can answer:
- “Is Weaviate healthy?”
- “Is backend configured to use it?”
- “Are we writing reminders to Weaviate?”
- “Are list endpoints reading from Weaviate (or falling back)?”
