---
category: operations
tags: [rview, rview-live, tony-dell, tailscale, podman, quadlet]
created: 2026-08-22
updated: 2026-08-22
---

# RView + Gemini Live on Tony-Dell

## What it is

Durable operational context for the `rview` remote media viewer and `rview-live` voice/text assistant running on `tony-dell`.

## Endpoints

| Service | Local (tony-dell) | Tailscale HTTPS | Caddy on tony-dell |
|---|---|---|---|
| `rview` UI | `http://tony-dell:8080/apps/rview/` | `https://tony-dell.taila0626a.ts.net:8443/apps/rview/` | `http://tony-dell:8080/apps/rview/` |
| `rview-live` UI | `http://tony-dell:8080/apps/rview-live/` | `https://tony-dell.taila0626a.ts.net:8443/apps/rview-live/` | `http://tony-dell:8080/apps/rview-live/` |
| `rview-api` | `http://127.0.0.1:3007` | `https://tony-dell.taila0626a.ts.net:8443/apps/rview/api/` via Caddy | `http://tony-dell:8080/apps/rview/api/` |
| `rview-live` WebSocket/API | `http://127.0.0.1:3008` | `wss://tony-dell.taila0626a.ts.net:8443/api/rview-live/` | `http://tony-dell:8080/api/rview-live/` |

Tailscale TCP serve is also enabled:
- `tony-dell.taila0626a.ts.net:3007` → `127.0.0.1:3007`
- `tony-dell.taila0626a.ts.net:3008` → `127.0.0.1:3008`

## View numbers

- Every view gets an auto-incrementing `view_number` starting at 1.
- Old persisted views without `view_number` are migrated on `rview-api` startup.
- The API accepts either `view_id` or `view_number`.
- A numeric `view_id` is interpreted as `view_number`.
- The UI shows `#<view_number>` in the top-right corner.
- The UI detects `?view=<number>` and uses `view_number` for all API calls.

## Media fallback

If an image, video, audio, or PDF fails to load, the UI swaps the element for an `<iframe>` pointing at the same URL and shows `fallback: <url>` in the status bar.

## How to talk to Gemini

From `https://tony-dell.taila0626a.ts.net:8443/apps/rview-live/`:

- `"Search for a cute cat picture and show it in the default rview"`
- `"Search the web for <topic>, read the first result, and create an HTML summary in RView"`

Gemini uses these tools:
- `web_search` — DuckDuckGo, no API key.
- `fetch_page` — fetches a URL and returns title/extracted text.
- `rview_show` / `rview_queue` / `rview_control` — update the remote viewer.

## Useful commands on `tony-dell`

```bash
# status
systemctl --user status rview-api rview-live mcp-rview

# logs
journalctl --user -u rview-api -n 50 --no-pager
journalctl --user -u rview-live -n 50 --no-pager

# full restart after a code change
systemctl --user stop rview-api rview-live
podman rmi -f localhost/rview-api:latest localhost/rview-live:latest
systemctl --user start rview-api-image-build rview-live-image-build
systemctl --user start rview-api rview-live

# reload Caddy
cd /home/tony/CascadeProjects/chaba
podman exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

## Rebuild gotcha

The Quadlet `.build` units are `Type=oneshot` with `RemainAfterExit=yes`. If you edit `rview-api.mjs` or `rview-live/server.mjs` on disk, you must remove the old image and restart the build unit, or the old container keeps running. `AutoUpdate=local` handles digest changes only when a new image is produced.

## Caddy routing

`/apps/rview/api/*` is proxied to `127.0.0.1:3007` and `/api/rview-live/*` to `127.0.0.1:3008`.

## chaba.h3 public URL (not yet verified)

`https://chaba.h3.gizmo-thailand.com/apps/rview/` and `/apps/rview-live/` route through the Node `proxy-server.mjs` to `tony-dell`. If it returns 502, the `chaba.h3` Node process is either still running the old `proxy-server.mjs` or the host cannot reach the Tailscale IP (`100.68.142.13`).
