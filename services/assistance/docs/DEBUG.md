# Assistance Stack – Debug & Verification

## Verify Status Endpoint (`/jarvis/api/verify/status`)

A read-only health/verification endpoint that checks both the jarvis-backend and the
jarvis-frontend bundle markers in a single request.

### What it checks

| Check | Description |
|---|---|
| `jarvis-backend.health` | GET `/health` on the backend returns HTTP 200 |
| `jarvis-backend.debug_status` | GET `/jarvis/api/debug/status` returns HTTP 200 |
| `jarvis-frontend.markers` | Fetches the frontend bundle and verifies DOM markers: `jarvis_status_details_open`, `/jarvis/api/debug/status`, `Hide status details` |

### Required env wiring

`JARVIS_PUBLIC_BASE_URL` must be set in the jarvis-backend container so it knows the
public URL of the frontend bundle to verify:

```yaml
# stacks/idc1-assistance/docker-compose.yml
services:
  jarvis-backend:
    environment:
      JARVIS_PUBLIC_BASE_URL: https://assistance.idc1.surf-thailand.com
```

An optional override `JARVIS_VERIFY_FRONTEND_BASE_URL` can be set to point at a
different host for the frontend bundle check (useful when frontend and backend are on
separate origins).

### curl example

```bash
curl -s https://assistance.idc1.surf-thailand.com/jarvis/api/verify/status | jq .
```

### PASS output

```json
{
  "ok": true,
  "checks": {
    "jarvis-backend": {
      "health": { "ok": true, "status": 200 },
      "debug_status": { "ok": true, "status": 200 }
    },
    "jarvis-frontend": {
      "markers": {
        "jarvis_status_details_open": true,
        "/jarvis/api/debug/status": true,
        "Hide status details": true
      },
      "ok": true
    }
  }
}
```

### Failure modes

| Symptom | Cause |
|---|---|
| `"jarvis-frontend": { "skipped": true, "error": "not_configured" }` | `JARVIS_PUBLIC_BASE_URL` (and `JARVIS_VERIFY_FRONTEND_BASE_URL`) are not set |
| `"is_html": true` in the frontend check | Bundle URL returned an HTML page (SPA fallback) instead of JS; check reverse-proxy routing |
| `"ok": false` on a backend check | jarvis-backend container is unhealthy or not reachable |

All checks are **read-only** – no secrets or mutations are involved.
