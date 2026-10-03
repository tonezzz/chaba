# idc02 offload audit — tony-dell user units

2026-10-03 · 96 `*.service` units inventoried on tony-dell via `systemctl --user show` ExecStart.
Classification: does the unit bind to tony-dell hardware/LAN/display/local-data, or is it portable compute?

## Verdict summary

| bucket | count | meaning |
|---|---|---|
| STAY — hardware/display/LAN | ~75 | physically bound to tony-dell |
| MOVE → idc02 | ~12 | portable batch/compute/report jobs |
| idc01 | 1 | better on the MDDB host than idc02 |

The 73-timer problem is real but the **service** inventory is mostly anchored — the offload win is concentrated in the report/audit/sync batch jobs, exactly the ones the jobs manifest (`ssot.jobs.yml`) is meant to own.

## MOVE → idc02 (portable — repo + MDDB + outbound ssh only)

| unit | runs | why portable | per-unit needs on idc02 |
|---|---|---|---|
| overnight-assessment | `orchestrate.py --workflow overnight` | compute over repo+MDDB | chaba checkout, mddb reach, gh creds |
| chaba-audit / chaba-audit-full | `node scripts/audits/run.mjs [--full]` | audit suite | repo, node |
| chaba-kb-audit | `auto-kb-quality-audit.mjs` chain | audit suite | repo, node |
| chaba-system-report | `audit-hosts.py` over 5 hosts | SSHs out to all hosts | ssh keys to tony-dell/omen/mn01/idc01/macbook |
| focus-dispatcher-overnight | `overnight-focus-review.py` | commits+pushes GitHub | chaba-tony-dell-style checkout, gh token, FOCUS_DISPATCHER_* env |
| devin-summaries-sync | `sync-devin-summaries.py` | devin summaries → MDDB | repo, mddb |
| devin-bank-distill | `distill-devin-bank.py` | devin bank distill | repo, mddb |
| devin-dispatch-watch | `devin-dispatch-watch` | dispatch queue watcher | verify queue source (MDDB/API vs local) |
| ada-flood-news | `flood-news-update.py --all` | RSS → MDDB | repo, mddb, outbound https |
| ssot-optimization-snapshot | `ssot-optimize.mjs` | repo analytics | repo, node |
| ha-card-snapshot | `snapshot-card.py --url https://tony-dell:8123/...` | remote API call | nothing host-bound |
| mcp-debug-h3-sync | `mcp-debug-h3-sync.sh` | repo sync | chaba-h3 checkout on idc02 |

## Better on idc01 (MDDB-local)

| unit | runs | note |
|---|---|---|
| ada-memory-backup | `backup-mddb-banks.py --git` | pulls MDDB banks → git; same-LAN as primary mddb beats cross-host |

## STAY — bound to tony-dell (~75)

| class | units |
|---|---|
| Display/seat | xfce-seat, lxqt-seat, xvfb-99, screen-timeout-daemon, xscreensaver(-systemd), chrome-cdp-headless, playlive-chrome, playlived (hosts the CDP browsers playlive MCP drives) |
| Barrier | barrier-client, barrierc, barrier-enforce-lan, barrier-pin-vt |
| Cameras/LAN | go2rtc, camera-monitor, camera-panel, cam-frame-refresh, update-cam-frame, cam-wall-cms, cam-wall-pull, xiaomi-token-refresh, plug-watch, network-scan-tony, walldance-cast |
| Cast targets | cast-browser-proxy, cast-ha-panel, cast-desktop@, cast-desktop-crop@, audit-cast |
| Guest LAN + ingress | chaba-guest-lan, ha-guest-lan, caddy-tony-dell |
| HA-local | tony-ha (container), ha-live (podman exec into tony-ha), ha-stall-watchdog, ha-config-backup (reads local /config), mha-state-push, michael-ha-mcp-tunnel |
| Datastores | chaba-postgres-16, redis, dnsmasq-postgre, weaviate |
| Local APIs/MCPs | chaba-guest, dev-miniapp-v0, secrets-console, mcp-focus, mcp-debug-cors, mcp-debug-sse, mcp-link-monitor, mcp-rview, mcp-rview-oauth-proxy, rview-state-server, yt-live-api, gods-eye-view-api, chaba-monitoring-dashboard, status-data-api, chaba-gemini-mic-test, notebooklm-keepalive |
| App services (containerized, local data) | raceman-php, raceman-web, yomi-api, trade-api, trade-automation, workflows-mcp |
| Tunnels | chaba-tunnel, playlive-macbook-tunnel, playlive-omen-cdp-tunnel, websockify-macbook, websockify-vms-mn01 |
| RAM caches | npm-cache-ram-cache, ms-playwright-ram-cache, ms-playwright-mcp-ram-cache |
| Local FS | rclone-gdrive (~/GoogleDrive), devin-cleanup (prunes tony-dell's own devin sessions), yomi-backup (pg_dump local postgres), mddb-standby-pull (tony-dell IS the standby target), status-data-api (bind-mounts local repo) |
| Host monitors | tony-dell-health-snapshot, tony-dell-monitor, tony-dell-mcp-health, chaba-dell-health-agent |
| Misc | obex, localsearch-3 (empty) |

## Migration order (proposed)

1. **Phase 1 — reports/audits** (safest, pure compute): `chaba-system-report`, `chaba-audit`, `chaba-audit-full`, `chaba-kb-audit`, `ssot-optimization-snapshot`, `overnight-assessment`. Needs: idc02 chaba checkout (exists), node, ssh keys.
2. **Phase 2 — sync/batch**: `devin-summaries-sync`, `devin-bank-distill`, `ada-flood-news`, `focus-dispatcher-overnight`, `devin-dispatch-watch`. Needs: MDDB reach (tailnet ✓), env/secrets copies, gh creds.
3. **Phase 3 — borderline**: `ada-memory-backup` → idc01; `yomi-backup` stays with postgres; `mcp-debug-h3-sync` needs chaba-h3 clone on idc02.

## Open checks before phase 1

- [ ] idc02 has `chaba` checkout + `~/.n/bin/node` (or equivalent node)
- [ ] idc02 ssh keyring reaches tony-dell/tony-omen/mn01/idc01/macbook (audit-hosts.py target set)
- [ ] Per-unit env/secrets (ada-pi-pwa.env, yomi env, FOCUS_DISPATCHER_*) copied or scoped to idc02
- [ ] Each moved unit disabled on tony-dell in the same change (no double-runs) — jobs manifest `host:` field enforces this
