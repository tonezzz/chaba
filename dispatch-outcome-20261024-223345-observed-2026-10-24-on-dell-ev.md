# Dispatch outcome — bench-verifier-inject-clobber close-out (mn01 → dell ~/evals)

## What I found

- Prior session had applied option (a) (`zz_heldout_` unique-prefix inject)
  to all m-tasks + both-era pre-run purge, and option (b)
  (`.preheldout` snapshot/restore) to t-tasks **on the success path only**.
- **New defect found:** `m1-mddb-follower-health`'s held-out files are the
  fix-commit versions of *tracked* repo tests. Injecting them as
  `zz_heldout_*.go` redeclares every test symbol in package `mddbd` →
  build-fail on **every** workspace (parent and fix alike). Unique-name
  injection is only valid for held tests that declare new symbols
  (m1-behavioral, m2 — verified zero collisions).
- t-task restore ran only on the success path: early `emit()` (bad pytest
  report) skipped restore and left injected files + `.preheldout` +
  `.verify-report.json`. m-tasks left injected `zz_` copies post-run.
- 23 historical workspaces carried residue: 6 t2 ws with 6 clobbered
  tracked tests each, 1 m1 ws with 2, ~16 untracked held-out files,
  3 zz_ leftovers, 15 `.verify-report.json`.

## What I changed (all on dell `~/evals/tasks/`, local state)

1. **m1-mddb-follower-health/verify/score.py** — rewritten to same-name
   replace semantics: heal stale `.preheldout` → purge untracked
   `zz_heldout_*` → snapshot targets → inject same-name → **restore in
   `finally`**. Also now preserves agent-created same-name files.
2. **m1-behavioral, m2-mddb-snapshot-proof** — kept `zz_` inject; added
   `finally` cleanup of injected files on all exit paths.
3. **t1-hint, t1-terrology, t2-terrology** — backup/restore moved into
   `finally`; stale `.preheldout` heal; injected-only files removed;
   `.verify-report.json` + verifier-created `.pytest_cache`/`__pycache__`
   pyc residue removed; per-file failures warn instead of aborting.
4. **Workspace sweep** — 23 ws: restored 38 clobbered tracked files via
   `git checkout`, removed 19 heldout-content/untracked residue files +
   15 reports + `/tmp` stray. Rescan: **0 remaining**.
5. **Board**: detailed fix comment posted; card moved backlog → review.
6. **SSOT trail**: `docs/ssot/jobs/bench/2026-10-24-verifier-inject-clobber-fix.yml`.

## Verified live

- m1: parent ed1ff11 → 0.0 (intended fix-coupled build-fail), fix c0850f0
  → 1.0 (11/11); pristine git status, idempotent second run.
- m1-behavioral: parent → 0.667, fix → 1.0; clean.
- m2: parent 60ac37c → 0.667, fix 497b982 → 1.0 (matches discriminator
  values); clean.
- t2/t1: pristine git status on normal, early-emit (report unreadable),
  and stale-`.preheldout`-heal paths.
- o1–o4 and lesson-polish never inject — confirmed, untouched.

## How to verify

- `ssh tony-dell 'cd /tmp/ws && python3 ~/evals/tasks/<task>/verify/score.py
  . ~/evals/tasks/<task>'` on any repo-task ws → `git status --porcelain`
  must be empty after.
- Re-run any verifier twice on one ws — same score, no residue.
- `find ~/evals/workspaces* -name 'zz_heldout_*' -o -name '*.preheldout'
  -o -name '.verify-report.json'` → empty.

## Caveats

- m1-mddb-follower-health remains fix-coupled by design (parent can't
  compile held tests referencing `rc.connected`); m1-behavioral is the
  interface-agnostic scorer. Not a regression — same gate as the original
  bare-copy verifier, now without clobbering.
- `.preheldout` heal can't recover an agent-modified file that was
  clobbered *without* a backup (old-era crash) — content unrecoverable,
  workspace restored to HEAD instead. Already the case.
