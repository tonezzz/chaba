# Dispatch outcome — sweep stale MDDB endpoint 100.74.146.0

## Result: done + verified

## What changed (worktree, 21 files)

Live defaults/repo files repointed to the idc03 leader `100.102.134.91`
(repo canonical pattern: IP literal + env-var override):

- `stacks/tony-dell/gev-gemini/bridge.py` — `GEV_MDDB_URL` default
- `stacks/idc01/doc-archive/doc_archive.py` — `MDDB_BASE` default
- `stacks/idc01/doc-archive/deploy.sh` — default HOST idc01→idc03, health-check
  bind → idc03, also scp `mirror-to-ha-www.sh` into the app dir
- `stacks/idc01/doc-archive/{doc-archive.env.example,README.md,doc-archive.container}`
  — bind/MDDB examples + comments
- `stacks/idc01/doc-archive/doc-mirror.service` — `TimeoutStartSec` 600→1800,
  `ExecStart` → `%h/.local/share/doc-archive/mirror-to-ha-www.sh` (deployed copy)
- `stacks/idc01/doc-archive/mirror-to-ha-www.sh` — curl `--max-time` 120→240
- `stacks/services/ada-scenario-runner/` ×4 units — `MDDB_BASE_URL` → leader
- `systemd/ada-flood-news.service` — comment → leader
- `.devin/skills/info-find/` (mjs + SKILL.md), `.agents/skills/auto-kb/` (mjs + SKILL.md)
- `experiments/ultralytics-yolo-ha/server.py` — comment example → idc03:3010
- `docs/kb/mddb-embedding-providers.md`, `docs/kb/ada-eval-jobs.md`
- NEW: `docs/ssot/jobs/infrastructure/2026-10-09-mddb-stale-endpoint-sweep.yml` (trail)

## On-host changes

- **idc03**: `doc-mirror` root cause was NOT the stale IP — the deployed
  `doc_archive.py`, mirror script, and env already pointed at the leader. The
  run legitimately needs ~22min; `TimeoutStartSec=600` killed healthy runs and
  individual Drive fetches intermittently exceeded curl `--max-time 120`
  (exit 28). Fixed without touching the live checkout (drift rule): installed
  the fixed script to `~/.local/share/doc-archive/`, repointed the installed
  unit's ExecStart, added drop-in `doc-mirror.service.d/10-timeout.conf`
  (TimeoutStartSec=1800).
- **tony-dell**: `gev-gemini` quadlet had no `GEV_MDDB_URL` → running image
  used stale baked default. Added `Environment=GEV_MDDB_URL=http://100.102.134.91:11023/v1`
  to `~/.config/containers/systemd/gev-gemini.container`, daemon-reload, restart.
- **idc01**: sed'd stale URL in `~/.config/systemd/user/ada-scenario-smoke.service.disabled` (disabled unit, hygiene).

## Verify

- `curl -m5 -X POST http://100.102.134.91:11023/v1/search` → **200**
- `doc-mirror.service` → **SUCCESS**, "synced 100 pages across 100 archives",
  22min inside TimeoutStartSec=1800
- `gev-gemini.service` → **active/running**, NRestarts=0, env carries leader URL

## Corrections to card premise

- `100.74.146.0` is **alive** — idc01 is the warm-DR mddb-follower
  (`:11123/v1/health` → 200). Only `:11023` (old leader) is dead.
  `ssot.values.yml:43` and `ssot.services.yml:160` were already **correct**
  records — deliberately left unchanged. `--add-host idc01...:100.74.146.0`
  quadlet lines are correct hostname→IP maps — left.

## Left alone (per card / out of scope)

- dated jobs/reports/cards/focus-inbox/backups/`.triage`/dispatch-outcomes
- `stacks/idc01/{mddb,mddb-follower,mddb-panel,ollama,open-notebook,camwall-edge,input-bridge}` — retired-host defs
- `ssot.idc01.yml`, `ssot.security.idc01.yml`, `ssot.audit.hosts.yml`,
  `ssot.health.home.datastore.yml` — correct idc01 host records
- `ssot.jobs.yml:427` — already documents the staleness
- `stacks/web/input-bridge/server.mjs` comment (exempt)
- secrets env files — only commented-out retired `MDDB_READ_URL` lines

## Not swept / follow-ups

- **mn01**: ssh publickey denied from idc03 — could not grep.
- **idc02**: checkout behind master (~20 stale files already fixed upstream —
  self-heals on pull).
- **tony-dell checkout**: `stacks/tony-dell/gev-gemini/bridge.py` still stale
  on disk until pull + image rebuild (runtime override already applied;
  single-writer rule — not hand-edited).
- **mddb-binlog-canary** card spec still instructs curling the dead leader
  URL — flagged via board comment (cards are out of edit scope).
