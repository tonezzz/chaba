# dispatch-outcome: fix _outcome_index in scripts/render-board.py

Card: render-board-worktree-rglob-slow (KNB-0162)
Runner: idc02 · Branch: dispatch/20261117-180908-fix-outcome-index-in-scripts-r

## What changed

`scripts/render-board.py::_outcome_index()` — replaced the per-worktree
`rglob` of `docs/ssot/jobs` with flat globs where outcomes actually live:

- `REPO.glob("dispatch-outcome-*.md")` — canonical merged location
- `REPO/docs/ssot/jobs` rglob — kept for the one legacy filed outcome
  (`jobs/<domain>/dispatch-outcome-*.md`)
- each `dispatch-wt-*` sibling: flat glob at worktree root + bounded
  2-level glob in `wt/docs/ssot/jobs` (covers `jobs/<domain>/` without
  the recursive walk)

## Measurements (as the card requested)

| host | dispatch-wt-* | _outcome_index (before) | full render |
|------|---------------|-------------------------|-------------|
| idc02 (this) | 46 | 0.84s → ~0.15s | ~11.4s |
| idc03 served | 0 | ~0s | 13.5s |
| tony-omen | 7 | 0.02s | **2m8s** |

Breakdown on tony-omen: `load_cards` 43s (900 YAML parses),
`compute_checks` 76s (git merge-base + git cherry subprocess per run
branch), `_outcome_index` 0.02s. The card's "~60-100s rglob" was not
reproduced on any measured host — the real render cost is YAML parsing
and per-branch git subprocesses. Follow-up filed:
**render-board-real-cost-git-subprocesses (KNB-0165)**.

## Bonus finding — the index was also wrong

The old scan rooted at `docs/ssot/jobs`, but sessions write outcomes at
the worktree ROOT (dispatch prompt contract + `SESSION_SCRATCH_RE` in
dispatch_repos). Result: the index held exactly 1 entry out of ~390
real outcome files — every "outcome" verification chip reported
missing. After the fix: 473 stems indexed; outcome checks 4/5 found
(the 5th card genuinely has no outcome). `render-board2.py` reuses
`_rb._outcome_index()` so board2 benefits too.

## Options decision

Chose none of (a)-(d) verbatim — the flat-root glob is strictly better:
O(dir entries) per worktree instead of O(files under jobs tree), and it
fixes the correctness bug. (d) `--no-outcomes` is not worth it: the
index is now ~0.15s; the inline render's real cost is elsewhere
(KNB-0165).

## Verify

```
python3 -c "
import importlib.util, time
s = importlib.util.spec_from_file_location('rb','scripts/render-board.py')
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
t=time.time(); idx=m._outcome_index()
print(len(idx), 'files', round(time.time()-t,3),'s')"
```
Expect ~470+ files in <1s on a worktree-heavy host. `python3
scripts/render-board.py` renders normally (verified, 902 cards).

lessons:
- dispatch-outcome docs live at worktree/repo ROOT, not docs/ssot/jobs — SESSION_SCRATCH_RE and the dispatch prompt are the contract; _outcome_index scanned the wrong dir for months (0/5 chips found).
- Measure before optimizing per card spec: the claimed 60-100s rglob was <1s everywhere; the real 2min render cost is load_cards YAML + per-branch git subprocesses (carded KNB-0165).
- render-board2.py shares _rb._outcome_index() — a fix in render-board.py propagates to the default board view automatically.
