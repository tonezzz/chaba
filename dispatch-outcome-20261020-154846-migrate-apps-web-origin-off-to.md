# dispatch outcome — migrate /apps web origin off tony-dell (OPS-0731)

## Result: done — /apps origin fully dell-free on idc02; card moved to review

Phase 1 (2026-10-19) stood the origin up on idc02; this session finished the job —
removed every remaining dell dependency and cleaned dell itself.

## What changed

**idc02 web origin** (`~/web-srv/caddy/Caddyfile`, deployed + validated + restarted):
- `/apps/ha/michael-dev` redir → `https://idc03.taila0626a.ts.net:8124/` (was stale dell:8124)
- `/snapshot` → `100.75.102.88:9005` (ha-live on omen)
- `/apps/vnc/ws` → `100.123.163.11:6082` (websockify→mn01:5900); added explicit `ws-mn01`/`ws-macbook`(:6080) handles
- `/apps/yt-corpus` now serves local `/srv/media/yt-corpus` (was proxying to dell) — new `-v` mount added to web.service
- dev-v0/gemini-mic routes already retired upstream; frigate stays `frigate:5000` (stopped by design → 502 expected)
- **zero** tony-dell/100.68.142.13 upstreams remain

**idc02 edge caddy** (`~/.config/caddy/Caddyfile`, validated + reloaded):
- `:8124` → idc03:8124 (michael-dev; was dell tony-test)
- `:9230` → idc03:3010 (input-bridge `INPUT_BRIDGE_PORT`)
- `:8446` → 503 retired (mcp-debug-sse has no live backend anywhere)

**Data:** yt-corpus rsync dell→idc02 running under `web-srv-sync.service` (systemd, survives teardown; 300M/8.9G at check-time, converges over next hours). Added corpus pull to the hourly sync so it stays fresh while dell's gdrive mount lives.

**Dell cleanup:**
- `web.container` quadlet parked → `migrated-off/`, container stopped
- `tailscale serve` table cleared — tailnet entry off dell entirely
- Boot-revived zombie quadlets parked: chaba-postgres-16, redis, trade-api, mddb, yomi-api, michael-dev, kk-ha (all verified live on idc03)
- `trade-automation` kept running (no idc03 counterpart) but `AddHost postgre` repointed dell→idc03 IP — it was silently writing dell's stale pg zombie
- dnsmasq-postgre left enabled (config already postgre→idc03)

**Repo/SSOT** (worktree commit `b79b552aa`, mirrored to idc03 served checkout for kanban-commit to land):
- `stacks/web/Caddyfile`, `docs/ssot/infrastructure/ssot.routes.yml`, `scripts/render-routes.py` (CUSTOM_BLOCKS dell IPs purged; generated output now matches canonical functionally), `stacks/web/public/apps/routes.json`, `ssot.system-map.yml` (edge front + kanban entries), new job doc `docs/ssot/jobs/infrastructure/2026-10-20-apps-web-origin-off-tony-dell.yml`

## Verified
- `https://idc02.taila0626a.ts.net/apps/{board,jam,gesture,vcast,vnc,node-red,yt-cache,yt-corpus,gev}/` all 200
- ws handshake `/apps/vnc/ws` → 101 end-to-end; `/apps/ha/tony-ha`→omen:8123, `/apps/ha/michael-dev`→idc03:8124
- `/snapshot` 200, `/api/yomi/health` 200, edge :8124/:9230 200, :8446 503
- QR flows fix themselves (origin follows location.origin — card's premise)

## Known remaining (non-blocking)
- yt-corpus freshness depends on dell's gdrive mount (hourly rsync); dell offline = last snapshot served. Long-term: rclone mount on idc02.
- trade-automation still runs ON dell — belongs to OPS-0725 job-estate sweep, not this card.

## Verify it yourself
`curl -skI https://idc02.taila0626a.ts.net/apps/board/` → 200; check `ssh tony-dell 'tailscale serve status'` → "No serve config"; `ssh idc02 'podman ps'` → web + caddy-edge running.
