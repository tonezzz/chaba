# Dispatch outcome — provision headless Playwright lane on idc02

Card: `playlive-idc-targets` (OPS-0439) · Branch: `dispatch/20261103-044920-provision-headless-playwright-` · Commit `920eb0656`

## What changed

**Provisioned (live on idc02):**
- `~/.local/playlive/` — canonical repo `playlived.mjs` + package.json (playwright pinned 1.62.0), node from `~/.local/node` (v22; system node18 too old), Google Chrome 156 via `npx playwright install --with-deps chrome`.
- `~/.config/systemd/user/playlived.service` — enabled+running, `PLAYLIVED_PORT=9240`, Nice=10 (unit also committed at `mcp-servers/mcp-playlive/playlived-idc02.service`). Linger already on.
- **Port 9240, not 9230**: idc02's tailnet :9230 is owned by caddy-edge (vcast signaling — its /health is a different service's). ufw denies public inbound except tailscale0+80/443, so the unauthenticated daemon is tailnet/localhost-only.

**Incidental repair:** tony-dell's `playlived.service` unit was missing (only the Nice=10 drop-in remained — the 2026-10-29 audit finding). Restored from `playlived-dell.service` and refreshed its `playlived.mjs` to canonical (dell's copy had drifted to a 60s idle timeout). A declared fallback that can't start isn't a fallback — now healthy on :9230.

**SSOT updates (this worktree, committed — not pushed):**
- `docs/ssot/infrastructure/playlive-hosts.yml` — `target_preference.status: active`; top-level `playlive_url` → idc02:9240; `hosts.idc02` added (no cdp — headless only); `per_host` (idc02→local, dell/omen→idc02); `failover` (idc02→dell, dell→local:9230, omen→dell); `self_heal.commands` rewired — idc02 restarts locally, dell/omen restart the remote idc02 daemon via ssh (dell's is compound: also resurrects its local failover daemon only when inactive); `session_selection` default/fallback updated.
- `docs/ssot/apps/ssot.apps.playlive.yml` — daemon rows, per-host/failover/self-heal/target-preference items, hosts table, decision guide, pinned-version note.
- `docs/ssot/infrastructure/ssot.audit.hosts.yml` — `playlived.service` declared in idc02 expected_services.
- `docs/ssot/infrastructure/ssot.health.home.api.yml` — new `playlived-idc02` http check.
- `docs/ssot/jobs/infrastructure/2026-11-03-playlived-idc02-provisioning.yml` — provisioning trail.

## Result / verification (all live-checked)

- `curl http://idc02.taila0626a.ts.net:9240/health` → `{"ok":true,...,"port":"9240"}`.
- End-to-end on idc02: POST /sessions (playwright-headless) → navigate example.com → title "Example Domain" → DELETE. Same cycle verified on restored tony-dell:9230.
- Loader resolution simulated for idc02/tony_dell/tony_omen/mn01: primary resolves to idc02:9240 (local on idc02), failovers to tony-dell.
- Live self-heal from tony-dell ran the compound command — restarted idc02's daemon remotely (uptime reset observed), rc=0.
- `target_preference.status: active`, order keeps idc01 last (retired/cold-batch — untouched, no ada services or mddb writes added).
- Pre-commit SSOT validation passed (IP warnings are pre-existing style notes).

## Caveats

- idc02 serves `playwright-headless` only — `chrome-live`/`playwright-chrome` need a CDP endpoint and fail on idc02 by design (use tony-dell/tony-omen).
- A browser on idc02 can only reach URLs idc02 can reach — services bound to another host's localhost can't be driven through the idc02 daemon; use that host's local daemon (`per_host` or explicit `remote_url`).
- Mirror copies `stacks/web/public/` + `public/docs/overview/ssot.apps.playlive.yml` are generated snapshots — left for the normal sync pipeline.
