# Dispatch outcome — nest-mgr-v2-actuation (attempt 2, idc02)

## What this attempt did

Attempt 1 (tony-dell, 09:04) completed the Phase-0 soak review and the
ghost-state fix, but its commit `0e8730d0e8e` was stranded: the
dispatcher pushed `dispatch/20261125-090427-...` to origin yet
auto-merge to master was rejected (fetch-first). Tony then answered the
open decision at 09:31: **stay-recommend**.

This attempt recovered the stranded work and closed the loop:

1. Merged `origin/master` (2f0af5d630) into the dispatch branch — clean.
2. Cherry-picked `0e8730d0e8e` → `c0b7265cd3`:
   - `stacks/services/nest-mgr/nest-mgr.py`: ghost-prune — actuation
     units absent from discovery are dropped after
     `UNIT_PRUNE_MISSES=30` ticks (~30 min); stale `held` verdicts clear
     when `fail_ticks` falls below threshold.
   - `tests/nest_mgr/test_nest_mgr_v2.py`: +4 tests (31/31 pytest pass).
   - `docs/ssot/jobs/devnest/2026-11-25-nest-mgr-v2-recommend-soak.yml`:
     the ~6-day recommend-mode soak evidence doc.
   - `stacks/services/nest-mgr/test-actuation.py`: gate matrix still
     21/21 pass.
3. Re-verified live pilot state (read-only, ~10:20 ICT):
   - idc02/con01/mn01 all `nest-mgr.service` active, mode=`recommend`,
     installed `nest-mgr.py` md5 `affd0aeb…` == Phase-0 commit
     `c4a7ab375bb` — zero drift since the 09:05 check.
   - idc02 `manager-state.json`: 137 actions, all `held /
     not-allowlisted`; zero executions. Ghost `ada-code.service` still
     present in state (expected — fix ships on next deploy).
   - `kk-mac-model-status.service` still the only genuine failure on
     idc02 (missing-script bug, carded OPS-1348; a restart cannot fix
     it — correctly held as not-allowlisted).
4. Recorded Tony's decision in the soak doc (`decision:` block) →
   `a2bc839931`.

## Result

- Phase 0 (spec + recommend-mode on idc02/con01/mn01, state-file
  logging, zero execution) is complete, deployed, and soak-verified.
- The one defect the soak exposed (ghost actuation units) is fixed in
  repo with test coverage; it reaches pilots on the next nest-mgr
  install — no deploy was performed (not authorized by this card).
- Phase 1 (guarded auto-restart) is deferred per Tony's stay-recommend
  answer; the soak doc lists the suggested path (resolve
  timer-alert-idc02-kk-mac-model-status, name 1–2 allowlist candidates
  per pilot, flip ONE host first — mn01 or idc02).
- Phase 2 work-stealing remains unstarted, correctly gated behind the
  restart pilot.

## How to verify

- `git log --oneline origin/master` after merge contains `c0b7265cd3`
  and `a2bc839931` (or their merged equivalents).
- `python3 -m pytest tests/nest_mgr/test_nest_mgr_v2.py` → 31 passed;
  `python3 stacks/services/nest-mgr/test-actuation.py` → 21/21.
- On any pilot: `cat ~/.local/share/nest/mode` → `recommend`;
  `md5sum ~/.local/share/nest/nest-mgr.py` → `affd0aeb…` until next
  deploy, then `5fa70240…`.
- Soak evidence + decision:
  `docs/ssot/jobs/devnest/2026-11-25-nest-mgr-v2-recommend-soak.yml`.

## Notes for the operator

- The old dispatch branch `dispatch/20261125-090427-...` is now
  redundant (its tip commit is cherry-picked here); merge-sweep can
  retire it.
- If/when Tony names allowlist candidates, Phase 1 is a per-host flag
  flip (`~/.local/share/nest/actuation.on` + mode `guarded`) — no code
  change needed.

lessons:
- Dispatch auto-merge can strand a completed worktree commit when master moves mid-close; always check `git merge-base --is-ancestor <commit> origin/master` before assuming prior work landed — cherry-pick recovers it cleanly.
- `git show <sha>` on a commit only present on a fetched dispatch branch works after `git fetch origin <branch>` — no need to check out the branch.
- nest-mgr recommend mode emits a `held` action per standing gate at ~hourly resend; a large actions[] count is normal, executions are the signal to watch (zero so far).
