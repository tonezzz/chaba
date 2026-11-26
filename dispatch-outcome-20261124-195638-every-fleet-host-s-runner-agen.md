# Dispatch outcome — runner-agent deploy propagation gap (OPS-1026), attempt 2

Card: `runner-agent-deploy-propagation-gap-repo-56a255`
Branch: `dispatch/20261124-195638-every-fleet-host-s-runner-agen`
Session worktree: tony-dell `dispatch-wt-20261124-195638-every-fleet-host-s-runner-agen`

## Why this attempt exists

Attempt 1 (idc02, branch `dispatch/20261124-184257-every-fleet-host-s-runner-agen`,
commits `b72a53d32a` + `83c3e92ffce`) did the real work — found that
auto-propagate already existed twice (`_self_update()` at pass start and
`sync-runner-tools.sh` at git-safe-pull tail) and fixed the actual break
(master's stale `runner_agent` pin blocking sync-runner-tools fleet-wide
while `_self_update` bypassed the pin). The branch pushed to origin but
merge-sweep aborted on a conflict in `scripts/devin/runner-tooling.manifest.json`.
Tony answered the merge-conflict request: **"resolve — let devin resolve
the conflict and land it"**.

## What this session did

1. Fetched `dispatch/20261124-184257-every-fleet-host-s-runner-agen`
   (`83c3e92ffce`) from origin — this worktree's remote refspec only tracks
   master, so a plain `git fetch` did not surface it; fetched the ref
   explicitly.
2. Diagnosed the conflict: single-line, both sides bumped
   `tools.runner_agent.sha256` from base `d0a103cb…`:
   - master → `9a42dc07…` (commit `15c70d856b0`, pin catch-up for the
     UNMODIFIED runner-agent.py — master never took the branch's code change)
   - branch → `b879b47f…` (pin for the branch's MODIFIED runner-agent.py
     carrying `_self_pin_ok`)
   Verified `sha256sum` of merged `scripts/board/runner-agent.py` =
   `b879b47f…` — the branch pin is the correct resolution.
3. Merged FETCH_HEAD into this branch (which sat on origin/master
   `ad7b3dfd0c8`) with `--no-ff`; resolved the manifest to `b879b47f…`;
   committed as merge `0b9a1e86836`. Pre-commit hooks passed (15s pytest
   gate timed out non-blocking; SSOT validation green — the new jobs yml
   validated).
4. Verified: `pytest tests/board/test_runner_self_update.py
   tests/board/test_runner_tooling_contract.py` → **13 passed**.
5. Re-fetched master (`ad7b3dfd0c8..558640d999d`): zero file overlap
   between newly-landed master commits and this branch's six changed
   paths — the eventual merge into master cannot re-conflict on content.
6. Live fleet check (the card's verify criterion, observable early):
   `~/.local/bin/runner-agent` sha256 == repo `scripts/board/runner-agent.py`
   == `9a42dc07…` on tony-dell, mn01, idc03, tony-omen — the master's pin
   catch-up already re-armed `sync-runner-tools.sh` and the fleet
   self-converged with no manual scp. Once this branch lands, pin →
   `b879b47f…` and the new `_self_pin_ok`-gated build propagates the same
   way on the next `chaba-repo-sync`/`runner-agent.timer` cycle.

## Notes for the closer

- The work is a **merge commit** (`0b9a1e86836`) whose second parent is the
  old dispatch branch tip — both attempt-1 commits are ancestors, so
  merging this branch into master lands everything.
- `docs/ssot/ssot.dev-system.assessment.yml` was left modified-then-reverted:
  the pre-commit `ssot-optimize` gate runs `dev-system-assess.py
  --metrics-only`, which rewrites that file in the worktree on every
  armed-checkout commit. Unrelated churn — do not commit it from dispatch
  worktrees.
- Attempt-1's full analysis/runbook is in
  `docs/ssot/jobs/kanban/2026-11-24-runner-agent-deploy-propagation.yml`
  (status: done) and `dispatch-outcome-20261124-184257-every-fleet-host-s-runner-agen.md`.

lessons:
- This worktree's `remote.origin.fetch` refspec is master-only — dispatch
  branches on origin need an explicit `git fetch origin <branch>` (or
  `git fetch origin <sha>`) before they're reachable.
- `.husky/pre-commit`'s ssot-optimize gate runs `dev-system-assess.py
  --metrics-only`, dirtying `ssot.dev-system.assessment.yml` in whatever
  checkout commits — revert it before close-out or the worktree looks dirty.
- Merge-conflict resolution for pin manifests: resolve to the pin matching
  the MERGED source file's sha256, not to either side's pin — verify with
  `sha256sum` on the post-merge tree.
