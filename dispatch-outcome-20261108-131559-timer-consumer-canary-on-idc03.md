# Dispatch outcome — timer-alert-idc03-consumer-canary (2026-11-08)

## Verdict
The `consumer-canary.service` "failure" was the canary working as designed: `scripts/audit/consumer-canary.py` exits 1 whenever it finds live retired-hostname references and posts them to the standing card. Journal on idc03 confirmed every flagged run printed findings then `status=1/FAILURE` — no crash, no broken unit.

## Findings fixed (both live consumers of retired `tony-dell.taila0626a.ts.net`)

1. **mn01 Caddyfile.mn01 `/apps/board*`** — a live-only `handle` block added 11-07 ~09:56 when `caddy-mn01.service` was stood up proxied board traffic to dead `tony-dell:443` (was 502ing; first canary hit 11-07 17:21). Repointed live upstream to `https://idc02.taila0626a.ts.net:443` (canonical `/apps` origin since the 10-20 migration), `caddy reload` via admin API, `/apps/board/` → 200 through `mn01:8080`. `stacks/mn01/Caddyfile.mn01` updated to match live (drift resolved).

2. **ada-ha `chaba-admin` dashboard, Node-RED panel** — iframe still pointed at `tony-dell…/apps/node-red/?v=2` (open since ~10-30; an earlier fix dropped only the `:8080` port). Fixed externally at ~13:19 ICT mid-session (live websocket config + `.storage/lovelace.chaba_admin` both verified → `idc02…/apps/node-red/?v=2`, 200). Repo snapshot `docs/home-assistant/dashboards/ada-ha-chaba-admin-current.json` re-synced via `sync-ssot-from-live.sh --instance ada-ha` — it had captured the stale URL at 13:16, 3 min before HA flushed the fix to disk.

## Verification
- `systemctl --user start consumer-canary.service` on idc03 → **CLEAN (9 greps + dashboards)**, `ExecMainStatus=0`, `Result=success` — twice consecutively (13:19, 13:20).
- `curl http://127.0.0.1:8080/apps/board/` on mn01 → 200 (through the repointed idc02 upstream).
- `curl https://idc02.taila0626a.ts.net/apps/node-red/` → 200 (iframe target).
- Live ada-ha lovelace config + storage file both grep-clean for `tony-dell`.

## Changes in this worktree (commit 9b851d738, dispatch branch — not pushed)
- `stacks/mn01/Caddyfile.mn01` — added `/apps/board*` handle → idc02:443 (matches live)
- `docs/home-assistant/dashboards/ada-ha-chaba-admin-current.json` — re-synced sanitized snapshot
- `docs/ssot/jobs/monitoring/2026-11-08-consumer-canary-timer-alert.yml` — investigation trail

## Board
- `timer-alert-idc03-consumer-canary` → **done** (resolution comment posted)
- `consumer-canary-standing-retired-hostnam-6aa4a2` → resolution comms posted

## Follow-up worth carding
`consumer-canary`'s exit-1-on-findings semantics keep tripping timer-sentinel into filing alert cards even though findings already go to the standing card. Options: wrap the timer to exit 0 (report via board-api only) or teach the sentinel this unit's exit-code means "findings posted". Noted in the trail file's `follow_ups`.
