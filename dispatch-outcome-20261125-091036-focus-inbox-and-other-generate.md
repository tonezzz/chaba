# Dispatch outcome — reconcile-local-conflicts-expire-stale-n-00974b

## What changed

`scripts/board/reconcile-local-conflicts.py` — non-card `.local-conflict-*`
files no longer accumulate forever:

- New `expire_noncard()` gate on both non-card branches: non-`.yml` files in
  the cards dir (`reconcile_one`) and `docs/ssot/**` strays (`run()`).
- A file expires only when ALL hold: the `CONFLICT_RE` base (canonical)
  exists — upstream-wins verified; the file is older than
  `RECONCILE_NONCARD_TTL_S` (default 86400s, age from the `-YYYYMMDD-HHMMSS`
  suffix with mtime fallback); and the archive move succeeds.
- Expired files are **moved** to `RECONCILE_NONCARD_ARCHIVE`
  (default `~/.local/share/chaba-reconcile-archive/`, repo-relative path
  preserved, `.N` on collision) — outside the checkout, so the tree goes
  clean while the dropped local side stays auditable.
- Fresh (<TTL), orphan (no canonical — may be the only copy), and
  unparseable-suffix files keep the existing flag-on-recent behaviour;
  flag text now distinguishes `no canonical base — kept` from
  `needs manual reconcile — file kept`.
- Card-path (`.yml`) reconcile/merge logic untouched.

Trail doc: `docs/ssot/jobs/kanban/2026-11-25-noncard-conflict-expiry.yml`.

## Result

- `python3 scripts/board/reconcile-local-conflicts.py --selftest` — OK
  (extended: stale+canonical expires to archive, run()=0; fresh+orphan
  kept+flagged, run()=1).
- `--dry-run .` on this worktree — exit 0, no conflicts present.
- `py_compile` clean; jobs YAML validated with `yaml.safe_load`.

## How to verify on a real host

Next `chaba-repo-sync` / `chaba-served-mirror-sync` tick (they run
`git-safe-pull.sh`, whose EXIT trap invokes the reconciler): any stale
non-card conflict moves to `~/.local/share/chaba-reconcile-archive/`,
`git status` goes clean, no new timer-alert. Tune via
`RECONCILE_NONCARD_TTL_S` / `RECONCILE_NONCARD_ARCHIVE` env.

## Notes

- Deploy is via the normal chaba-repo-sync flow — no push/deploy done
  here per dispatch rails; the change lands when this branch merges.
- The 2026-11-13 manual cleanup already cleared the live backlogs; this
  prevents recurrence.

lessons:
- Reconcile flag text should distinguish orphan (no canonical — never
  expire) from fresh (inside TTL) — collapsing them hides real anomalies.
- Filename `-YYYYMMDD-HHMMSS` suffix is a more stable age source than
  mtime for conflict files.
