# dispatch-outcome — dispatch-merge-sweep re-verification #2 (2026-11-18)

## What happened

Second consecutive user-triggered re-dispatch of card `dispatch-merge-sweep`
(the first, session 20261118-204621, finished ~7 min before this one started and
its no-change outcome is already merged — this worktree's base contains commit
c3633b71fa). The card spec shipped 2026-10-08 (OPS-0200); both re-dispatches
confirm the same verdict: **nothing to build — spec already shipped and live.**

Independently re-verified in this worktree rather than trusting the prior
outcome:

## Verification against the card spec

`scripts/board/merge-sweep.py` (1703 lines) implements every spec bullet:

- **Enumerate** doing/review cards with `action.type=dispatch` + session —
  `load_dispatch_cards` / `sweep_card()`; session resolved via action.task_id →
  claim.session → `started devin-task-<id>` comms → runner-agent state.json.
- **Locate worktree on recorded runner** via the meta.json pattern
  (`~/.local/share/devin-dispatch/tasks/<tid>/meta.json`) — `REMOTE_SESSION_PROBE`
  with `dispatch-wt-<id>` and repo-clone-branch fallbacks.
- **Verify runner worktree HEAD clean** (dirty → comms flag once, never
  auto-committed) and ahead of base via `dr.merge_state()` vs origin/<default>.
- **Fetch** `git -c core.sshCommand=ssh fetch <runner>:<worktree> HEAD` —
  `fetch_session()` (the `-c` override defeats the repo's pinned GitHub-only
  key). Fallbacks: session branch on origin, then relayed git bundle via
  `$DISPATCH_DIR/patch-inbox/`.
- **Merge policy = stop-and-report**: `merge_strict()` in a detached worktree of
  the served checkout — ANY conflicted path aborts and posts a card request
  naming the files; never resolves either side. Clean merge pushes
  `HEAD:<base>` + posts card comms. Shadow-path check (gitignored-dir symlinks)
  blocks the 2026-10-10 `.venv` incident class.
- **dispatch_repos reuse** — `import dispatch_repos as dr`; `merge_state()`,
  `repos()`, `gc_worktree` semantics all reused per spec.
- **Timer**: spec asked for `merge-sweep.timer` on dell (~15min). Architecture
  evolved — served writer moved dell→idc03 (OPS-0725), and merge-sweep is
  sub-check #1 of `board-janitor.py` under `board-janitor.timer` on idc03
  (`OnUnitActiveSec=15min`, `ssot.jobs.yml` job `board-janitor`, OPS-1244d;
  rendered unit: `systemd/generated/idc03/board-janitor.timer`). Documented
  deviation, same cadence, correct host for single-writer safety.
- **Targets**: `SERVED` map = chaba→`~/CascadeProjects/chaba-tony-dell`,
  ada-voice→`~/CascadeProjects/ada-voice`; `MERGE_SWEEP_TARGETS` env override;
  `served_repo()` falls back to `dr.repos()`. The spec's `ada-pi` resolves
  through `REPO_ALIASES`/`BUILTIN_REPOS` to the ada-voice checkout (repo renamed
  2026-10-14, card ada-pi-rename-ada-voice).
- **Zombie lane**: `REMOTE_ZOMBIE_PROBE` + `zombie_probe()` flag `devin-task-*`
  units >6h old (ZOMBIE_AGE_H) with >60min idle (ZOMBIE_IDLE_MIN) in card comms
  — flag-only, never auto-kills (the 32h cue-fit case). Activity = newest mtime
  of cgroup processes' `devin_*.log` + task dir.

## Acceptance status

Already evidenced live on 2026-10-08 (3 stranded branches fetched off runners,
true upstream conflicts → card requests naming files, 2 cards verified-stamped)
— per card comms. Acceptance holds.

## Test result

`python3 -m pytest tests/board/test_merge_sweep.py` — **41/41 pass** (9.9s),
same as the prior verification.

## Board state

- Posted one card comms line documenting re-dispatch #2 + verification.
- No requests raised, no card fields mutated (field-ownership rule; the
  sweep's own `drain_verified` re-closes the card once this session's
  close-out lands).
- No code changes — any unsolicited edits to this 1700-line production script
  would be risk without benefit.

## Note for the board

This is the second no-op re-dispatch of a done card in 7 minutes. The card is
`doing`/`running` because re-claiming reopens workflow fields; if repeat
re-dispatches of shipped cards become a pattern, the fix is upstream (dispatch
should not re-queue verified cards), not in this repo file.

## How to verify

```
python3 -m pytest tests/board/test_merge_sweep.py -q
grep -n "merge-sweep" scripts/board/board-janitor.py          # sub-check #1
grep -A8 "id: board-janitor" docs/ssot/infrastructure/ssot.jobs.yml
cat systemd/generated/idc03/board-janitor.timer               # OnUnitActiveSec=15min
```
