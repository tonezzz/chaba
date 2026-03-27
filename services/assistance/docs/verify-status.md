# Operator Verification: `/jarvis/api/verify/status`

A read-only endpoint for operators to confirm that the Jarvis stack is healthy
and correctly wired end-to-end.  It runs three sub-checks and returns a single
aggregated JSON result.

## Endpoint

```
GET /jarvis/api/verify/status
```

Accessible locally via:

```bash
curl -s http://127.0.0.1:18018/jarvis/api/verify/status | jq .
```

Or through the host reverse proxy:

```bash
curl -s https://<host>/jarvis/api/verify/status | jq .
```

## What it checks

| Check name | What it does |
|---|---|
| `jarvis-backend` | Calls `/health` on the backend and asserts `ok: true` |
| `jarvis-backend-debug-status` | Calls `/jarvis/api/debug/status` and asserts `ok: true` |
| `jarvis-frontend` | Resolves the frontend's bundled JS asset URL and checks it for required bundle markers |

## Response shape

The `checks` field is a **list** of objects, one per sub-check.  The top-level
`ok` is `true` only when every sub-check passes.

```json
{
  "ok": true,
  "checks": [
    {"name": "jarvis-backend",              "ok": true, "details": {"git_sha": "abc1234", "uptime_seconds": 3600}},
    {"name": "jarvis-backend-debug-status", "ok": true, "details": {"status": "ok"}},
    {"name": "jarvis-frontend",             "ok": true,
      "url": "http://jarvis-frontend:80/jarvis/assets/index-Abc123.js",
      "is_html": false,
      "markers": {"jarvis_status_details_open": true}
    }
  ]
}
```

### Failure modes

| Symptom | Meaning |
|---|---|
| `"skipped": true, "error": "not_configured"` in a check entry | The env var needed for that sub-check is not set — the check is skipped rather than failing hard |
| `"is_html": true` in the `jarvis-frontend` check | The resolved bundle URL returned an HTML document instead of JS; typically a SPA fallback / Caddy routing misconfiguration |

## Environment variables (stack compose)

Both variables are wired in `stacks/idc1-assistance/docker-compose.yml`.

| Variable | Default in compose | Purpose |
|---|---|---|
| `JARVIS_PUBLIC_BASE_URL` | `http://jarvis-backend:8018` | Base URL the endpoint uses when running the backend sub-checks.  The default resolves correctly inside the Docker network with no extra config required. |
| `JARVIS_VERIFY_FRONTEND_BASE_URL` | _(empty — optional)_ | Override the frontend root URL used for the bundle marker check.  When unset the endpoint falls back to the internal `jarvis-frontend` service. |

To override for a non-standard deployment, add the variable to
`stacks/idc1-assistance/.env`:

```dotenv
JARVIS_PUBLIC_BASE_URL=http://127.0.0.1:18018
JARVIS_VERIFY_FRONTEND_BASE_URL=http://127.0.0.1:18080
```
