# Dispatch outcome — apps-yml-host-url-still-tony-dell-x42 (attempt 2)

## What changed

Migrated every stale `tony-dell.taila0626a.ts.net` host reference in the apps
index chain to the real `/apps` web origin — **idc02** (`web.service` serving
`~/web-srv/public`, fed hourly by `web-srv-sync.timer` from the idc03 served
checkout; mn01 mirrors via caddy public dir). The 2026-10-20 OPS-0731
migration moved the origin off tony-dell but the registry/files kept the old
hostname.

- `stacks/web/public/apps/apps.yml` — 47 entries repointed: 42
  `host: tony-dell` + 5 `host: yomi` → `host: idc02` /
  `host_url: https://idc02.taila0626a.ts.net`. **Zero**
  `tony-dell.taila0626a.ts.net` refs remain (was 47).
- `stacks/web/public/apps/lab/index.html` — `hostLabel` fallback
  `'tony-dell'` → `'idc02'` (same logic as `apps/index.html`).
- `docs/ssot/apps/ssot.apps.yml` — `apps-hosts`: `tony-dell` group renamed to
  `idc02` (web-origin description + note); `yomi` group deleted, its 5 apps
  folded under `idc02`; `ada-voice` + `speaker-enroll` added to the `idc03`
  group (they were wrongly listed under the old tony-dell group).
- `stacks/web/public/ssot.apps.yml` — stale public copy: same tony-dell→idc02
  group rename + yomi fold.
- `scripts/apps-yml-generate.py` — `BASE_URL` and all host/host_url defaults
  tony-dell → idc02 (regen can't reintroduce the retired refs).
- `scripts/apps-health-sync.py` — fallback defaults → idc02;
  `SYNCABLE_HOSTS` `{tony-dell, mn01}` → `{mn01}` (idc02 content arrives via
  web-srv-sync, not the `~/.config/caddy/public` rsync path).
- `docs/ssot/infrastructure/ssot.health.home.apps.yml` — regenerated from
  apps.yml: 55 services, all web-origin checks now
  `https://idc02.taila0626a.ts.net` (also picked up `app-percussion`, missing
  since the last regen).
- `scripts/audit/consumer-canary.py` — new `idc02:apps-index` grep covering
  the deployed `~/web-srv/public/apps/{apps.yml,index.html}` on idc02 —
  closes the verify-by-surface gap (canary previously covered only the
  web-origin Caddyfile, not the deployed webroot).
- `docs/ssot/jobs/infrastructure/2026-11-26-apps-yml-host-url-migration.yml`
  — job trail.

## Result / verification

- `grep -c tony-dell.taila0626a.ts.net stacks/web/public/apps/apps.yml` → **0**
- Host distribution: idc02 ×47, mn01 ×4, idc03 ×4; all touched YAML parses;
  no duplicate ids/hrefs.
- Live consumer proof: `https://idc02.taila0626a.ts.net/apps/`,
  `/apps/cams/`, `/apps/yomi/`, `/apps/lab/` all return 200.
- Canary grep shape proven end-to-end: `ssh idc02 "grep -nE '<pat>'
  ~/web-srv/public/apps/apps.yml ~/web-srv/public/apps/index.html"` runs
  clean — it currently reports the 47 stale refs in the *deployed* copy,
  which is correct canary behavior until `web-srv-sync` picks up the merge
  (~15 min cadence after idc03 pulls master), then self-clears.
- `consumer-canary.py` still contains 2 `tony-dell.taila0626a.ts.net` refs —
  those are the `RETIRED_HOSTS` default it audits for; intentional.

## Why attempt 1 failed (and what differed)

Attempt 1 (2026-11-24, tony-macbook) did the same analysis and reported
[done] on the card but left 16 files uncommitted — checkpoint failed
(worktree 103 commits behind), merge-sweep scored it a failed attempt. This
run committed everything on the dispatch branch.

## How to verify after merge

1. `git show master:stacks/web/public/apps/apps.yml | grep -c
   tony-dell.taila0626a.ts.net` → 0
2. After web-srv-sync: `ssh idc02 'grep -c tony-dell.taila0626a.ts.net
   ~/web-srv/public/apps/apps.yml'` → 0
3. Next consumer-canary run posts no `idc02:apps-index` findings.

## Follow-ups noticed (not fixed — out of scope)

- `apps/lab/index.html` ENDPOINTS block still lists `idc01.taila0626a.ts.net`
  URLs (Ada ws/PWA, MDDB stats) — idc01 prod role retired 2026-11-14.
- ~33 other scripts still reference `tony-dell.taila0626a.ts.net` — parent
  `tony-dell-full-migration` scope.
- `scripts/make-apps-pwa.py` fallback description `'{name} on tony-dell'` —
  cosmetic string, not a URL.

lessons:
- dispatch close-out requires COMMITS on the dispatch branch — attempt 1 did all the analysis but left 16 dirty files and was scored a failure; commit before writing the outcome doc
- apps.yml host/host_url is sticky: apps-yml-generate.py only fills missing fields, so producer defaults in scripts + ssot.apps.yml apps-hosts must be repointed together or regen reintroduces retired hosts
- consumer-canary GREPS entries are (label, ssh-host, remote-cmd) tuples; grep exit 1 = clean, >1 = UNAUDITABLE finding — multi-file grep output strips fine through is_ignored()
- idc02 /apps origin is ~/web-srv/public via web.service — NOT ~/.config/caddy/public; apps-health-sync rsync only feeds the mn01 caddy mirror now
