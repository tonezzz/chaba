# Dispatch outcome — raceman-php-placement-decision

**Card:** `raceman-php-placement-decision` (docs/ssot/kanban/cards/raceman-php-placement-decision.yml)
**Date:** 2026-11-25 · **Runner:** tony-dell · **Result:** DONE — path 2 chosen, implemented, verified

## What was found

The card's 2026-11-11 premise was half-stale. Verified live on 2026-11-25:

- `raceman-php.service` on **tony-dell is ACTIVE** (running since 2026-11-16 09:49 +07; container `raceman-php` Up 8 days, php-fpm listening `0.0.0.0:9001`). Someone had already restarted it after the card was filed.
- `raceman-web.service` on **tony-omen** is active, host-network nginx on `:8083`; no raceman-php unit/container exists on omen.
- Omen's `~/CascadeProjects/chaba-raceman/nginx.conf` still had `fastcgi_pass 127.0.0.1:9001` (omen localhost — dead) → `/apps/raceman/api/*.php` returned **502**.
- Raceman is **not static-only**: `course-manager.js`, `state-manager.js`, `yaml-editor.js`, `raceman.js` fetch `api/{list,load,save,save-course}.php` for course persistence. The PHP API is file-backed (`apps_data/raceman/state.json` + `public/apps/raceman/courses/*.yml` in the host-local `~/CascadeProjects/chaba-raceman` checkout — not a git repo on either host).
- php-fpm on dell has no `listen.allowed_clients` restriction; TCP 9001 reachable from omen over tailnet.

## Decision: path 2 — keep raceman-php on tony-dell, repoint omen nginx

- Path 1 (php on omen) rejected: file-backed course data would split-brain across two host checkouts.
- Path 3 (retire) rejected: JS actively calls the PHP API for save/load.
- Path 2 matches existing SSOT intent (`ssot.services.yml` already declared `host_port: 100.68.142.13:9001`) and required only a one-line nginx change.

## What changed

**Live (outside worktree):**
- `tony-omen:~/CascadeProjects/chaba-raceman/nginx.conf` — both `fastcgi_pass 127.0.0.1:9001;` → `100.68.142.13:9001;` (backup `nginx.conf.bak-20261125` kept alongside). `systemctl --user restart raceman-web.service` applied it.
- `tony-dell:~/CascadeProjects/chaba-raceman/nginx.conf` — same sed for parity (unused on dell; dell raceman-web is retired).

**Repo (this worktree, dispatch branch):**
- `docs/ssot/infrastructure/ssot.services.yml` — raceman-php gained `host: tony_dell` + decision note; raceman-web note records the tailnet fastcgi upstream.
- `docs/ssot/infrastructure/ssot.audit.hosts.yml` — dell `expected_services` raceman-php note; omen `expected_services` raceman-web note; omen `expected_absent` gained `raceman-php.service` (ghost guard).
- `docs/ssot/infrastructure/ssot.health.home.web.yml` — raceman-php note records backend role + outage window.
- `docs/ssot/apps/ssot.apps.raceman.yml` — deployment section documents the PHP backend placement.
- `docs/ssot/jobs/infrastructure/2026-11-25-raceman-php-placement.yml` — full decision record, evidence, rollback, follow-ups.

## Verification

- `GET http://127.0.0.1:8083/apps/raceman/` on omen → **200**
- `GET /apps/raceman/api/list.php` → **200 JSON** course list (was 502)
- `GET /apps/raceman/api/load.php?course=tabsai-ws8-track3` → **200** real overrides JSON
- `GET /apps/raceman/api/save.php` → **400 `{"error":"empty body"}`** — php-fpm executing app code
- `GET /apps/yt-live/<file>` → **200** — co-tenant media on same nginx unaffected
- `nginx -t` clean; all five edited YAML files parse; `ssot-validate-all.mjs` run in background

## Gotcha worth remembering

`nginx.conf` is a **single-file bind mount** into the container. `sed -i` replaces the inode → container kept serving the old config; `nginx -t` and `nginx -s reload` both operated on the stale file (502 persisted). Fix required `systemctl --user restart raceman-web.service`. For single-file mounts: edit in place or restart — reload is not enough.

## Follow-ups (non-blocking)

- `~/CascadeProjects/chaba-raceman` is not under git on either host — the nginx fix exists only as host files; a future redeploy from a canonical source must template `fastcgi_pass` per host or it regresses to `127.0.0.1:9001`.
- Course API now depends on tailnet dell↔omen; static app still serves if dell is down (save/load 502s) — acceptable for a LAN tool, noted in SSOT.
- php-fpm :9001 is `0.0.0.0` on dell (LAN+tailnet); could be tightened with `listen.allowed_clients` later.

lessons:
- Single-file bind mounts + `sed -i` = stale config inside container; `nginx -s reload` reloads the OLD inode. Restart the unit (or edit in place) after sed -i on a mounted conf.
- Card premises go stale: raceman-php was already restarted on dell 2026-11-16 before this dispatch ran — always re-verify live state before executing a "restore" path.
- `systemctl --user is-active` on a nonexistent unit prints `inactive` — check `systemctl status`/`cat` before concluding a unit exists-but-stopped.
