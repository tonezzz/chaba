# Host Reboot Verification Runbook

Standard procedure for planned reboots of `tony-omen` and `tony-dell`.
Canonical checklists live in `docs/ssot/infrastructure/ssot.operations.yml`
(`transition.pre_shutdown`, `transition.post_restart`, `host_notes`).
This runbook is the concrete, copy-paste version of those steps.

Rules:

- Steps marked **must** must pass before continuing. If one fails, mark it
  `blocked` and note why — do not force ahead.
- Record short evidence per step (one line: what was checked + result).
- Always use tailnet hostnames (`tony-dell`, `tony-omen`) or Tailscale IPs.
- MCP health tooling runs **over SSH on tony-dell**. When tony-dell is the
  host being rebooted, expect `mcp-health`/`mcp-focus`/`mcp-debug` MCP calls
  to fail during the window — run the equivalent commands locally/SSH instead,
  or follow `ssot.tony-dell-failover.yml` to switch wrappers to local stdio.

---

## Phase 0 — Before either host reboots

```bash
# 1. Focus/session state captured
cd /home/tony/CascadeProjects/chaba && git status --short   # commit or stash pending work

# 2. Baseline health snapshot (from tony-omen, via mcp-health MCP)
#    mcp-health: check_health            # save the summary + unknowns
#    mcp-debug:  mcp_health(host=...)    # preflight for each target host

# 3. Tailscale up on all hosts
ssh tony-dell tailscale status && tailscale status
```

## tony-dell — pre-shutdown

tony-dell is the headless primary: Postgres, Redis, Weaviate, Yomi, raceman,
Home Assistant, mcp-debug-sse, gpu-queue, Caddy, ha-live.

- [ ] Baseline `mcp-health` snapshot saved (Phase 0).
- [ ] Yomi/Postgres: no in-flight writes that cannot be interrupted. If the
      window is long, follow `docs/ssot/infrastructure/ssot.yomi-failover.yml`
      to fail yomi-api/postgres back to tony-omen.
- [ ] Warn: mcp-debug/mcp-health/mcp-focus MCP tools and
      `https://tony-dell...:8444` ha-live will be down during the window.
- [ ] Optional: stop non-essential units (playlived, michael-dev).
- [ ] `ssh tony-dell 'systemctl --user list-units --state=failed'` — note any
      pre-existing failures so they aren't blamed on the reboot.

## tony-dell — post-reboot

```bash
# 1. Reachability
ping -c 2 tony-dell
ssh tony-dell 'tailscale status && uptime'
ssh tony-dell 'systemctl --user list-units --state=failed'

# 2. Containers (podman rootless should auto-start)
ssh tony-dell 'podman ps --format "{{.Names}} {{.Status}}"'

# 3. Key endpoints (from tony-omen)
curl -s -o /dev/null -w '%{http_code}\n' https://tony-dell.taila0626a.ts.net:8080/apps/tony-live/  # Caddy (tailnet :8080 is HTTPS-only)
curl -s http://tony-dell:3001/health                                       # gpu-queue
curl -s http://tony-dell:3000/api/yomi/health                              # yomi-api
curl -s -o /dev/null -w '%{http_code}\n' https://tony-dell.taila0626a.ts.net:8444  # ha-live

# 4. mcp-health: check_health  — confirm no critical error/degraded,
#    and previously-"unknown" items (e.g. Helm Dashboard, Trade API,
#    MDDB stats endpoints) are back or accounted for.

# 5. Physical display + barrier (monitor is on iGPU DP-2, not the AMD card)
ssh tony-dell 'pgrep -a Xorg'                       # expect ":1 vt7" (xorg-seat.service)
ssh tony-dell 'systemctl --user is-active lxqt-seat.service barrier-client.service'
ssh tony-dell 'journalctl --user -u barrier-client -n 3 --no-pager'  # "connected to server"
ssh tony-dell 'cat /sys/class/drm/card1-DP-2/status' # expect connected (else check cable)
```

- [ ] `mcp-debug` MCP tools respond again (preflight `mcp_health(host="tony_dell")` ok).
- [ ] Resume focus via focus-dispatcher if it was paused.
- [ ] Screen black after reboot → check `/sys/class/drm/card1-DP-2/status`
  (monitor may be on the other GPU or unplugged), then
  `systemctl status xorg-seat` / `systemctl --user status lxqt-seat`.

## tony-omen — pre-shutdown

tony-omen is the interactive/GPU primary: ollama, imagen2, playlive(d),
gpu-queue, barrier-server, sensor-reader, caddy web, bserver.

- [ ] Save interactive/Devin session state; GPU work cannot migrate.
- [ ] Checkpoint or stop GPU jobs (ollama/imagen2/txt2vid).
- [ ] Barrier client on tony-dell will disconnect — expected.
- [ ] Baseline `mcp-health` snapshot saved (Phase 0).

## tony-omen — post-reboot

```bash
uptime && tailscale status                       # online as 100.75.102.88
nvidia-smi                                        # GPU present, only Xorg
systemctl --user status barriers.service weaviate-index.timer
systemctl status cpufreq-limit.service
curl -s http://100.75.102.88:8001/health          # sensor-reader
mount | grep -i gdrive                            # Google Drive mounted
ping -c 2 tony-dell
# mcp-health: check_health — tony-omen services healthy,
# intentionally-off services (llama-router, imagen2, txt2vid,
# activepieces, frigate, chaba-health-monitor) remain off.
```

---

## Lessons from the 2026-09-07 tony-dell reboot

Evidence: `2026-09-07 tony-dell reboot: 42/52 healthy after remediation; 1 error (ha-live, pre-existing), 2 unknown (check-config).`

Fixed during recovery — all now persistent:

- **barrierc needs `DISPLAY=:20`** (Chrome Remote Desktop Xorg). Without it the
  client can't open a screen. Added `Environment=DISPLAY=:20` +
  `XAUTHORITY=/home/tony/.Xauthority` to `~/.config/systemd/user/barrier-client.service`
  on tony-dell. Also killed a stale `barrierc` targeting old LAN IP `192.168.1.48`
  (tony-omen LAN is now 192.168.2.x — prefer the tailnet IP `100.75.102.88`).
- **Physical display / barrier (final state, 2026-09-07)**: the monitor is on the
  **Intel iGPU `DP-2`**, not the AMD card. GDM autologin opens but the seat
  session exits immediately (unresolved; greeter is Wayland even with
  `WaylandEnable=false`), leaving a black screen. Permanent replacement, now
  enabled:
  - system unit `xorg-seat.service` — root `Xorg :1 vt7` on seat0
  - user unit `lxqt-seat.service` — `startlxqt` on `DISPLAY=:1`, waits for
    `/tmp/.X11-unix/X1`, then `sudo -n chvt 7`
  - `barrier-client.service` — `DISPLAY=:1`, waits for the X1 socket, target
    `100.75.102.88`. Note: the CRD session (`:20`) no longer gets barrier input.
  Post-reboot verify: `pgrep -a Xorg` (expect `:1`), `pgrep lxqt-session`,
  `systemctl --user status barrier-client` ("connected to server").
  To log in at the greeter instead: plug in a keyboard — the greeter is Wayland
  and barrierc can't attach to it.
- **tailscaled vs `0.0.0.0` port race**: `tailscale serve`/funnel entries and the
  `tailscale-serve-8080.service` system unit bind tailnet-IP ports at boot. Any
  container binding `0.0.0.0` on the same port gets `EADDRINUSE`. Resolution per
  user decision: containers bind loopback, serve handles tailnet.
  - `rview-api`: added `RVIEW_API_HOST` env support in
    `chaba-deploy/stacks/web/rview-api/rview-api.mjs` (build context is
    `chaba-deploy`, not `chaba-tony-dell`), set `RVIEW_API_HOST=127.0.0.1` in
    `~/.config/containers/systemd/rview-api.container`, rebuilt image.
  - `web` (Caddy): **there is no docker-compose on tony-dell** (docker = podman
    shim) and no systemd unit; the container had to be recreated manually with
    `podman run --network host` (the Caddyfile `bind`s host IPs). Compose file's
    `ports:` are decorative under host networking.
- **rview-live**: removed `Requires/After=rview-live-image-build.service` from
  `~/.config/containers/systemd/rview-live.container` — the build context path
  `/home/tony/CascadeProjects/chaba` doesn't exist on tony-dell. Kept
  `Requires=rview-api.service`. Runs the existing local image.
- **mddb has a ~4–8 min init** before binding :11023/:11024/:9000 — a silent
  "running but not listening" window is normal; check `journalctl --user -u
  mddb.service` for "Server initialization complete" before restarting it.
- **trade-automation** can race Postgres at boot (`database system is starting
  up`) — `systemctl --user restart trade-automation.service` after postgres is up.
- Known check-config gaps (not service failures): health check hits
  `http://tony-dell:9002` for Trade API but it binds `127.0.0.1:9002`; tailnet
  `http://tony-dell:8080` returns 400 because `tailscale-serve-8080` terminates
  HTTPS — use `https://tony-dell.taila0626a.ts.net:8080` or loopback/LAN.
- Pre-existing breakage (failed before and after): `gemini-live.service`
  not-found → ha-live `:8444` 502; `sync-to-hdd.service`; `mcp-debug-h3-sync`;
  `obex.service`; `dnsmasq-postgre.service`.

## Evidence record

Append one line per reboot to the session/focus log, e.g.:

```
2026-09-07 tony-omen reboot: 40/52 healthy, 0 error, GPU ok, tailscale direct; unknowns = dell-side endpoints (helm, trade-api, mddb stats).
2026-09-11 tony-omen reboot: post-reboot all checks pass, 0 failed units, GPU ok, journal vacuumed 44.7M; watch mddb-chat-widget health.
```

Related: `docs/ssot/infrastructure/ssot.operations.yml`,
`docs/ssot/infrastructure/ssot.tony-dell-failover.yml`,
`docs/ssot/infrastructure/ssot.yomi-failover.yml`,
`docs/ssot/infrastructure/ssot.health.home.*.yml`.
