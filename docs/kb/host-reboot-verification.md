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
curl -s -o /dev/null -w '%{http_code}\n' http://tony-dell:8080/api/status   # Caddy, expect 200
curl -s http://tony-dell:3001/health                                       # gpu-queue
curl -s http://tony-dell:3000/api/yomi/health                              # yomi-api
curl -s -o /dev/null -w '%{http_code}\n' https://tony-dell.taila0626a.ts.net:8444  # ha-live

# 4. mcp-health: check_health  — confirm no critical error/degraded,
#    and previously-"unknown" items (e.g. Helm Dashboard, Trade API,
#    MDDB stats endpoints) are back or accounted for.
```

- [ ] `mcp-debug` MCP tools respond again (preflight `mcp_health(host="tony_dell")` ok).
- [ ] Resume focus via focus-dispatcher if it was paused.

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

## Evidence record

Append one line per reboot to the session/focus log, e.g.:

```
2026-09-07 tony-omen reboot: 40/52 healthy, 0 error, GPU ok, tailscale direct; unknowns = dell-side endpoints (helm, trade-api, mddb stats).
```

Related: `docs/ssot/infrastructure/ssot.operations.yml`,
`docs/ssot/infrastructure/ssot.tony-dell-failover.yml`,
`docs/ssot/infrastructure/ssot.yomi-failover.yml`,
`docs/ssot/infrastructure/ssot.health.home.*.yml`.
