# Dispatch outcome — correction commands die at the confirm gate (attempt 2)

Card: `correction-commands-die-at-the-confirm-g-05902a` (OPS-0567)
Runner: tony-dell · Branch: `dispatch/20261016-144441-correction-commands-die-at-the`

## Prior failure, diagnosed

Attempt 1 was scored "no delivered work — head is an old base commit —
nothing committed". That was a merge-gate false-negative, not missing
work: the checkpoint `e1a79a2d7` and merge `22d2358cb` DID land Drop 11
(verified: both are ancestors of this worktree's HEAD, all eight
deliverable files present). Tony's `85ec42e86` already fixed the gate
itself (tri-state drop guard, depth-1 clone, stub-leak fixes).

## What this run verified (attempt 2's job: confirm the landed work)

- **Patches still apply** — `git apply --check` clean on ada-voice HEAD
  `5dc7665` for both
  `integrations/ada-voice/backend/realtime_provider.correction-command.patch`
  and `tool_guide.correction-command.patch`. The drop base has moved
  (`41020cf` → `5dc7665`, ~2 days of upstream drift) with no rot.
- **Not yet merged upstream** — `memory_directive`/`_MEMORY_DIRECTIVE`
  absent from ada-voice `backend/realtime_provider.py`; the drop is
  still pending, so no divergence.
- **Gate test green** — `pytest tests/ada/test_correction_command.py`:
  2 passed in 5.2s (depth-1 clone of the live ada-voice checkout, patch
  apply, then the 10 `_user_memory_directive`/`_memory_directed_call`
  unit tests under the real venv).
- **Docs intact** — README "Drop 11" install section present;
  `ssot.apps.ada-memory-banks.yml` write_policy text documents
  directive-authorization.

## What changed in this run

- `docs/ssot/jobs/ada/2026-10-16-correction-command-directive.yml` —
  job-trail record: decision, deliverables, verification evidence,
  deploy gate, residuals.
- This outcome doc.

## Result / status

**Verified intact, staged-not-deployed.** The fix is correct and
complete as staged patches; installing into ada-pi requires explicit
approval per the ada-voice deploy policy (dispatch cannot self-approve).
Install steps: `integrations/ada-voice/README.md` § Drop 11 — `git
apply` both patches on ada-voice `main`, copy
`tests/test_memory_directive.py`, run the standard deploy gates.

## How to verify

```
cd ~/CascadeProjects/ada-voice
git apply --check <chaba>/integrations/ada-voice/backend/realtime_provider.correction-command.patch
git apply --check <chaba>/integrations/ada-voice/backend/tool_guide.correction-command.patch
cd <chaba> && python3 -m pytest tests/ada/test_correction_command.py -x -q
```

## Comms note

board-api (127.0.0.1:8787) was inactive for most of this run (stopped
14:23; a queued restart by another session was still pending at end) —
progress comms could not be posted; this doc + the job-trail file carry
the record.

lessons:
  - A "no delivered work" merge-gate failure can be a ref/timing
    false-negative — check `git merge-base --is-ancestor <checkpoint>`
    before re-doing the work; the fix may already be merged.
  - Staged-drop verify: `git apply --check` directly in the target
    checkout is read-only and answers "does the patch still fit" without
    a clone.
  - board-api on tony-dell can be down mid-dispatch; don't block the
    deliverable on comms — record in the outcome doc and retry at end.
