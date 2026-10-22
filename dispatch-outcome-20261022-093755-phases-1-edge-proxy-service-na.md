# Dispatch outcome — tony-dell-full-migration (phases verify window)

Session: `devin-task-20261022-093755-phases-1-edge-proxy-service-na` on mn01.
Branch: `dispatch/20261022-093755-phases-1-edge-proxy-service-na` @ `57de510b`.

## State read

Phases 1–6 of the runbook were already complete before this session: edge
front on idc02, writer family on idc03, VPS APIs on idc02/03, backup chain on
idc02, LAN cohort on omen, and **dell powered off 2026-10-20**. This session
ran the phase-6 verify pass and found real breakage.

## What changed (live hosts)

- **idc03 — pg/redis port reconcile (was a ~31h outage):** the wave-2 quadlet
  `chaba-postgres.container` (deployed 10-21 09:36, committed today as
  35b91fa9) bound pg to tailnet **:5433** — every consumer expects
  `postgre`/100.102.134.91 **:5432**, so yomi-update-all/-active/-mddb-digest,
  gpu-queue-processor (648 refused connects) had been dead since deploy.
  Quadlet now publishes `127.0.0.1:5433` (litellm owns loopback :5432) +
  `100.102.134.91:5432`. Same-commit `chaba-redis.container` gained the
  missing tailnet `:6379` publish. Superseded `chaba-postgres-16.service` and
  `redis.service` parked (`*.parked`, disabled). Verified: pg answers 90
  tables, all three yomi units re-ran clean, gpu-queue polling again.
- **tony-omen — weaviate pair repointed:** `weaviate-index.service` and
  `weaviate-search.service` had `WEAVIATE_URL=http://tony-dell:8084` (dead).
  Now `http://100.123.163.11:8084` (idc02). Search verified end-to-end (real
  hits via mn01 embed proxy + idc02 weaviate); indexer is mid full-index run
  with no connection errors.
- **tony-omen — dead-dell units parked:** `mddb-tunnel` (fwd omen:9001→dell:9000,
  no consumers — mddb reachable directly at idc03:9000), `chaba-watch` (rsync
  source dark), `clip-sync-dell` (restart-looping). All stopped, disabled,
  renamed `*.service.parked`.
- **tony-omen — node-red flows repointed:** live `flows.json` had HA states →
  dell:8123 (now `https://tony-omen...:8123`), board-api → 127.0.0.1:8787 (now
  `https://idc03...:10000`), board2 probe → dell edge (now idc02 edge), plus
  "host=tony-dell" text. Restarted; probes verified from inside the container.
- **idc02 — disk pressure:** the pending board request (delete 2 stranded
  `*.UNVERIFIED` mddb dumps, ~11G) was answered by Tony and executed by
  another session at 16:39 — disk 93%→89%. Same-day good dumps confirmed on
  idc03 + gdrive.

## What changed (repo, commit `57de510b`)

- `stacks/idc03/chaba-postgres.container` — tailnet publish 5433→**5432**
  (+comment: loopback stays 5433, litellm owns 127.0.0.1:5432)
- `stacks/idc03/chaba-redis.container` — + tailnet publish `100.102.134.91:6379`
- `stacks/tony-dell/node-red/flows-cms-live-report.json` — same repoints as live
- `stacks/web/public/apps/` consumer fixes: `trade/tradecanvas-ui/app.js`
  (absolute `tony-dell:8080/api` → relative `/apps/trade/api` + scheme-aware WS),
  `ha/tony-ha/index.html` (Local → `192.168.2.67:8123`), `ha/index.html` label,
  `index.html` (hostLabel + headless-primary → idc02), `lab/index.html` (5 links
  → idc02 front), `ai-hub-extension/sidepanel.html` (preset → idc02),
  `tailscale-funnel/index.html` (rewrote reachability section for post-dell
  reality)
- **NEW `docs/ssot/infrastructure/ssot.migrated-units.yml`** — the card's
  required `{data_dirs, unit_file, secrets_env, front_name}` declaration per
  migrated unit (first pass, `pending` markers where a secrets path is
  unverified)
- **NEW `docs/ssot/jobs/infrastructure/2026-10-22-tony-dell-migration-verify-window.yml`**
  — findings/lessons record

## Board updates

- `tony-dell-full-migration`: progress + verify-window summary comments
- `migration-stragglers-orphaned-units`: resolution status (4/6 verified or
  fixed, 2 dell-local items deferred to phase 7)

## Still open (carded, not blockers)

- `/data/report.json` (report-feed JSON) and `/apps/notebooklm-cookies`
  (cookie bridge) routes died with dell — producers need re-homing or the
  links/presets removed
- Dell-local `ha-auth-watch`, `network-scan-tony` — unreachable until dell
  returns; phase-7 items
- `secrets-collect` dell leg fails weekly while dark (expected)
- `DOC_PRINT_SSH=tony-dell-m2m` in 6 ada envs on idc03 — tracked on
  `dell-off-repoint-followups`
- omen `~/.config/devin/mcp_config.json` still has tony-dell endpoints
  (postgres :5432, imagen, weaviate, home-assistant/michael-dev/michael-ha
  URLs) — also tracked on `dell-off-repoint-followups`

## How to verify

- `ssh idc03 'ss -tln | grep -E "5432|6379"'` → `100.102.134.91:5432` +
  `:6379` listeners; `systemctl --user is-active chaba-postgres chaba-redis`
- `ssh idc03 'systemctl --user start yomi-update-all.service'` → exits 0
- `ssh tony-omen 'curl -s -X POST http://127.0.0.1:3002/search -H "Content-Type: application/json" -d "{\"query\":\"test\",\"limit\":1}"'` → real results
- `ssh tony-omen 'systemctl --user is-active weaviate-search weaviate-index'`
- `curl -s https://idc02.taila0626a.ts.net/apps/board2/` → 200
