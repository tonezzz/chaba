# Dispatch outcome — reconcile-noncard-conflicts-never-resolve

Card: `reconcile-noncard-conflicts-never-resolve` (ref KNB-0168)
Branch: `dispatch/20261125-143933-observed-2026-11-17-on-idc03-s`
Commit: `c87fc3a5ad9`

## What was found

The card observed 16 focus-inbox `*.local-conflict-*` files (dated
2026-11-11) re-flagged as "non-card conflict kept" on every
`git-safe-pull`/`kanban-commit` exit on the idc03 served checkout. Two
separate gaps in `scripts/board/reconcile-local-conflicts.py`:

1. **Orphans never expire.** The TTL expiry added earlier the same day
   (`reconcile-local-conflicts-expire-stale-n-00974b`) only archives a
   non-card conflict when its canonical base exists. Focus-inbox entries
   are moved to `processed/` or deleted after handling, so their
   conflict copies have no canonical base → `expire_noncard` returned
   `"orphan"` forever → flagged forever.
2. **Dedup didn't quiet the noise.** `flag_card`'s 48h
   `FLAG_DEDUP_H` window suppressed the *board* flag but the caller
   still printed `reconcile: non-card conflict kept: …` to stderr and
   counted a leftover (rc 1) on every single run.

## What changed

`scripts/board/reconcile-local-conflicts.py`:

- New `NONCARD_ORPHAN_TTL_S` (env `RECONCILE_NONCARD_ORPHAN_TTL_S`,
  default **7d**). `expire_noncard` now applies it when the canonical
  base is missing: orphans quarantine to
  `~/.local/share/chaba-reconcile-archive/` (same archive as
  canonical-backed expiry) instead of living in-tree forever. The move
  preserves the only copy of the dropped local side — quarantine, not
  deletion — addressing the earlier "orphan may be the only copy"
  concern with a longer grace window for the flag to be seen.
- `flag_card` now returns a status (`flagged` / `dedup` / `lost` /
  `dry`) and no longer prints a per-file dedup line. Both non-card call
  sites (the `docs/ssot` stray scan and non-`.yml` files inside the
  cards dir) skip the stderr "kept" line and the leftover count when
  the status is `dedup` — a repeat run inside the 48h window is
  completely silent with rc 0.
- Card (`.yml`) conflict failures are unchanged — still loud every run,
  since they may hold board writes.
- Module docstring + comments updated.

`tests/board/test_reconcile_local_conflicts.py`: orphan now
quarantines after TTL (recent orphan kept+flagged, ancient archived);
new `test_already_flagged_noncard_is_quiet` asserts second run = rc 0
+ empty stderr; `expire_noncard` status coverage updated for the
orphan TTL.

`docs/ssot/jobs/kanban/2026-11-25-reconcile-noncard-conflicts.yml`:
job doc with policy, knobs, and gotchas.

## Verification

- `python3 scripts/board/reconcile-local-conflicts.py --selftest` — OK
  (covers fresh/orphan kept+flagged, quiet second run, ancient-orphan
  archival).
- `pytest tests/board/test_reconcile_local_conflicts.py` — 6 passed.
- `pytest tests/board/test_runner_agent_reconcile.py` + reconcile file
  — 14 passed.
- `tests/test-kanban-commit.sh` integration suite: 82 passed / 6
  failed — **identical failures on the parent commit** (verified via
  `git archive HEAD~1`): merge-fallback sections I/J and a
  runner-tooling pin-check fixture issue, all unrelated to this change
  (untouched code paths: `git-safe-pull.sh` merge logic,
  `merge-card-yaml.py`).
- **Card verify criterion, scratch-repo e2e** (isolated `HOME` +
  `CHABA_SERVED_CHECKOUT`, script copied into fixture so the
  served-checkout flag path ran):
  - Run 1 (rc 1): fresh + recent-orphan conflicts flagged once on
    `ops-local-conflict-guard`; a 2020-dated orphan was archived to
    `~/.local/share/chaba-reconcile-archive/docs/ssot/focus-inbox/…`
    with content preserved.
  - Runs 2 and 3: **zero stderr, rc 0** — already-seen conflicts silent.

## Deploy note

No deploy performed (dispatch rule). The change takes effect on the
served checkout (`~/CascadeProjects/chaba-tony-dell` on idc03) when this
branch merges and `chaba-repo-sync`/`git-safe-pull` picks it up — the
served checkout runs the script from its own tree, so the 16 observed
files will quarantine/quiet on the first post-merge reconcile pass
(files dated 2026-11-11 are already past the 7d orphan TTL → archived
immediately, content preserved under the archive root).

## Lessons

- Orphan exemption in `expire_noncard` was the forever-flag path:
  focus-inbox `processed/` moves delete the canonical base, so "may be
  the only copy" cases are common, not rare — archive (preserve) beats
  keep-in-tree.
- Flag dedup suppressed the board write but not the caller's stderr/
  leftover accounting — quieting has to happen at the call site, so
  `flag_card` now returns a status instead of `None`.
- `_flag_key` strips the `.local-conflict-<ts>` suffix: a genuinely new
  conflict on the same path inside 48h of a flagged one is also quiet.
  Accepted trade-off (same-file recurrence = same event).
- `tests/test-kanban-commit.sh` has 6 pre-existing failures on this
  host (merge-fallback I/J + runner-tooling pin fixture) — verify
  against `git archive HEAD~1` before assuming a regression.
