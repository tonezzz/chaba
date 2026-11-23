# dispatch 20261123-110440 — storage-rebalance-underused

## What changed / was found

**Underused signal landed (worktree, committed on dispatch branch):**
- `ansible/playbooks/disk-headroom.yml` + `templates/disk-headroom.j2` —
  new `underused` mount state: pct < 50 OR avail >= 100 GiB on mounts
  >= 10 GiB, only when not already warn/crit. Verified end-to-end with a
  real playbook run: `idc02: underused: /`, `mn01: underused: /`,
  `tony-dell: warn: /; underused: /dell-backup, /timeshift`,
  `tony-omen: underused: /, /data`.
- `scripts/ada/disk-trend-watch.py` — same thresholds as a report-only
  `underused` state (env `DISK_TREND_UNDERUSED_PCT=50`,
  `_FREE_GIB=100`, `_MIN_SIZE_GIB=10`); never opens cards, counted in
  run summary + meta. `--selftest` PASS including new underused assert.
- `stacks/idc03/mddb/mddb-backup-offload.sh` (NEW) — archives
  `~/mddb-backups` beyond newest-1-per-instance to
  `idc02:~/mddb-backups-idc03` via rsync; remote-df guard, local prune
  only after remote size match, flock, board-api alert. e2e tested.
- `docs/ssot/jobs/infrastructure/2026-11-23-storage-rebalance-plan.yml` —
  full survey, move plan, capacity analysis.

**Live survey findings:**
- idc03: 91%, 28.8 GiB free, **+6.18 GiB/day -> full in ~4.7d**
  (critical). Dead/movable weight: stale `mddb.db.precompact-20261111`
  31G, devnest model mirror 33G (declared disposable; con01 primary has
  37G superset), mddb-embed leftover 2.8G, mddb-backups 59G,
  mddb-ops live db 63G.
- tony-dell: 89%, 24.1 GiB free, **+8.29 GiB/day -> full in ~2.9d**
  (more urgent). 40G is ONE Chrome `file-cache` CacheStorage origin
  (tony-ha.surf-thailand.com PWA — unbounded, will regrow until capped);
  models 34G; BUT `/dell-backup` 851 GiB + `/timeshift` 329 GiB free on
  the same host — dell's fix is local placement, not cross-host.
- Underused capacity: idc02 159G free, con01 140G, mn01 150G.
- Capacity verdict: rebalance, don't resize — all three VPS have
  identical 290G disks; con01/idc02 are CPU-bound (load 9-19), not
  disk-bound.

## Result / gate

No prod deletes, moves, or deploys executed (destructive ops need
explicit approval). **Board request raised** on the card offering the
batch: (a) idc03 deletes ~66G, (b) deploy offload -> idc02 ~40G,
(c) dell models -> /dell-backup 34G, (d) clear chrome file-cache 40G.

## How to verify

- `cd ansible && ansible-playbook playbooks/disk-headroom.yml` —
  underused rows/summaries per host.
- `python3 scripts/ada/disk-trend-watch.py --selftest` — PASS.
- `python3 scripts/ada/disk-trend-watch.py --report` (on idc03 served
  checkout after merge) — `<== UNDERUSED` flags.
- `MDDB_BACKUP_DIR=<fake> MDDB_BACKUP_OFFLOAD_TARGET=<host>:<dir> bash
  stacks/idc03/mddb/mddb-backup-offload.sh --dry-run` — eligible list.

## Follow-ups

- Carded as separate work when approved: mddb-ops 63G migration to
  idc02 (biggest lever); ada-ha PWA unbounded `file-cache` cap (root
  cause of dell's 8.3 GiB/day); dell CascadeProjects worktree GC.

lessons:
- tony-dell's real rebalance target is LOCAL: /dell-backup (916G, 8%
  used) and /timeshift (379G, 9%) — don't assume cross-host is needed;
  check `df` for sibling mounts before planning rsync.
- idc03's single biggest dead file is mddb.db.precompact-* safety
  copies in ~/.config/containers/mddb-ops/data — compaction flows
  should delete or offload these after verify.
- Chrome Service Worker CacheStorage can balloon (40G, one PWA
  'file-cache' origin); du the profile Default/"Service Worker" dir
  before blaming real data.
- board-api /comment can return "board write lock saturated" — retry
  after ~5s rather than dropping the comm.
