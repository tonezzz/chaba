# Dispatch outcome — auto-reconcile .local-conflict card files

Card: kanban-local-conflict-reconciler (branch dispatch/20261010-103407-auto-reconcile-local-conflict-)

## What changed

- **scripts/board/reconcile-local-conflicts.py** (new) — reconciler for
  `docs/ssot/kanban/cards/*.yml.local-conflict-*` files. Loads both sides
  under the `/tmp/board-api.lock` flock and merges the dropped local
  side into the canonical card:
  - `comms[]` — union, dedup on (at|ts, from, text), time-sorted
  - `requests[]` — merged by id; per entry the more-resolved/newer side
    wins each key (open < answered < closed)
  - `ask{}`, `action{}` — per-key union won by the side with the later
    `updated`; `pipeline{}` stages deep-merged per stage `at`
  - board scalars (column, note, awaiting_action, claim, review_kind) —
    newer side wins; `updated` = max
  - all other keys — canonical (upstream) wins; conflict-only keys kept
  - identical conflicts are deleted with no card write; merges get an
    audit comms line
  - failure path: conflict file stays; canonical card gets comms +
    column=review; orphan/unreadable canonicals flag
    `ops-local-conflict-guard` (kanban-commit alert_card pattern)
  - non-card `.local-conflict-*` under docs/ssot/ are never auto-merged
    — flagged on the alert card
  - CLI: `--dry-run`, `[repo-dir]`, `--selftest`
- **scripts/git-safe-pull.sh** — EXIT trap `_post_pull_reconcile` runs
  the reconciler on every exit path (gated on the repo check), so even
  aborted rebases reconcile the conflict files their resolved steps
  produced; reconcile failure never fails the pull. Also: same-path
  conflicts in several rebase steps within one `$TS` second now get
  `-N`-suffixed conflict filenames instead of silently overwriting the
  preserved side.
- **docs/ssot/jobs/kanban/2026-10-10-local-conflict-reconciler.yml** —
  runbook/job doc (policy, verify steps, gotchas).

## Result / verification

- `python3 scripts/board/reconcile-local-conflicts.py --selftest` — OK
  (comms union/sort/dedup, requests merge by id, newer-wins scalars,
  conflict-only keys preserved, orphan + unparseable flag paths,
  end-to-end file consumption).
- End-to-end scratch repo (bare origin + two clones, divergent commits
  on the same card): `git-safe-pull.sh` rebased, produced
  `t.yml.local-conflict-<ts>`, trap merged column/action/comms into the
  canonical card and deleted the conflict file; result lands as a
  normal working-tree modification for the next kanban-commit tick.
- `bash -n` + `py_compile` clean. `node` is absent on idc02 so
  `ssot-validate-all.mjs` could not run — the new job doc parses via
  `yaml.safe_load`; run the full validator on tony-dell if wanted.
- Live count check: no `*.local-conflict-*` files currently in the
  worktree.

## Notes for review

- Merge lands as an uncommitted working-tree change post-pull —
  kanban-commit's next tick commits+pushes it (up to ~15min lag).
- Commit: b447ec30 on the dispatch branch (not pushed).
