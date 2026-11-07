# dispatch-outcome: repoint-3-dead-ha-mcp-bridges

Card: ha-mcp-endpoint-repoint-fdf629 | Date: 2026-10-26 | Result: DONE — all 3 endpoints live and verified.

## What changed

**Live config** — `~/.config/devin/mcp_config.json` (tony-macbook, backup `.bak-20261026`):
- `home-assistant`: already pointed at `http://tony-omen:9584/...` — verified live, unchanged.
- `michael-dev`: re-added → `http://idc03:9585/private_B3WMIAChoseTpDS7fwgwRw` (had been dropped in the 2026-10-22 dead-server cleanup).
- `michael-ha`: `tony-omen:19584` → `http://100.80.105.88:9584/private_oBVC604-FnxgBDP00t1L9g` (direct to host; no tunnel hop).

**Host change (idc03)** — `~/.config/containers/systemd/michael-dev.container` gained `PublishPort=127.0.0.1:9585:9585` + `PublishPort=100.102.134.91:9585:9585` (tailnet-only); backup `.bak-20261026`. `systemctl --user daemon-reload && restart michael-dev.service` — container healthy, UI :8124=200, MCP :9585 answers. Rollback: restore .bak, reload+restart.

**SSOT** — endpoint fields synced in `ssot.mcp.yml` and `ssot.home-assistant.mcp.yml` (required), plus stale references in `ssot.services.yml`, `ssot.home-assistant.michael.yml`, `ssot.home-assistant.michael-ha.topology.yml`, `ssot.home-assistant.michael.dev.yml`, `ssot.home-assistant.yml`, `ssot.home-assistant.howto.yml`, `ssot.operations.yml`, `ssot.security.tony-dell.yml` (dell listeners marked RETIRED). Job trail: `docs/ssot/jobs/infrastructure/2026-10-26-ha-mcp-endpoint-repoint.yml`.

## Findings worth noting

- tony-omen is back; the evacuated tony-ha container serves MCP on :9584 (python3, 0.0.0.0).
- `michael-ha-mcp-tunnel.service` no longer exists on dell — it lives on **tony-omen** (`ssh -L 0.0.0.0:19584 → homeassistant:9584`), which is why `tony-omen:19584` still answers. Kept as a secondary alias; can be retired after a consumer audit.
- `michael-dev` on idc03 was running but only published 127.0.0.1:8124 — the MCP port was never exposed on the host since the 2026-10-09 migration; that was the actual break.
- `michael-dev-parity.service` on tony-omen is failed (pre-existing; likely stale after the idc03 move) — followup noted.
- Other hosts' `mcp_config.json` copies may still carry the old tony-dell URLs — same repoint applies there.

## Verification

- `curl -X POST <endpoint> {"method":"initialize"}` → all three return `ha-mcp 8.7.0` JSON-RPC result.
- `mcp_list_tools` on `home-assistant` and `michael-ha` OK (session bindings); michael-dev takes effect next session — endpoint verified directly.
- All edited YAML parses clean; `git add -A` staged on the dispatch branch (no push).
