# Dispatch outcome — evidence 2026-11-13 (ada drop-10 merge-gate rot)

Card: `chaba-merge-gate-ada-drop10-rotted` · runner: tony-omen
Branch: repair branch of the done-condition (rebase, not retire).

## What was wrong

`tests/ada/test_cast_loop_breaker.py::test_patches_apply_clean` failed on a
clean tree: five of drop 10's six patches still applied, but
`backend/realtime_provider.cast-loop.patch` reported `diverged` — and with no
sibling `merged`, `drop_guard_ok` judged the pending drop's base rotted and
red-held the merge gate (kk-mac-supervised-probe-20261113 held;
kk-mac-lane-live-probe hit 2026-11-12).

Root cause was context-line rot, not a semantic conflict: upstream ada-voice
rewrote the `DEFAULT_ADA_INSTRUCTIONS` bullet two lines below the patch's
insert anchor ("Live status: use nest_status…" → "Questions about ongoing
work… are memory questions…"). The patch itself — three instruction bullets
(TARGET FIDELITY / FRUSTRATION BUDGET / FAILED-ACTION LOOP) — is still
absent upstream (verified: no `stop_and_ask`, no TARGET FIDELITY text in
ada-voice HEAD `07119b1`), so the drop is still legitimately pending and
repair was the right branch over retirement.

## What changed

- `integrations/ada-voice/backend/realtime_provider.cast-loop.patch` —
  regenerated against ada-voice `main` @ `07119b1` (was staged vs `5dc7665`).
  Method: depth-1 clone inside the worktree, inserted the patch's exact 19
  added lines at the surviving anchor, `git diff` → patch. Byte-identical
  hunk content; only context lines, hunk offsets, and index hashes changed.
- `integrations/ada-voice/README.md` — drop-10 install note records the new
  base and the rebase reason; Verified section gained a 2026-11-13 rebase
  entry.
- `docs/ssot/jobs/ada/2026-11-13-ada-drop10-cast-loop-rebase.yml` — job
  record with evidence, resolution, and a re-run recipe for the next rot.
- Board comment posted to `chaba-merge-gate-ada-drop10-rotted`.

## Result

- `python3 -m pytest tests/ada/test_cast_loop_breaker.py -q` → **2 passed**
  (the apply-gate AND the full `cast_wrong_target_loop` scenario run on the
  patched tree via the ada-voice venv — the stronger signal that the drop
  still functions).
- Rebase-branch done-condition met: guard passes on this tree; the held
  merges (kk-mac-supervised-probe-20261113 et al.) should clear once this
  lands. The "subsequent unrelated dispatch merge" leg is by construction —
  the gate was this test, now green.
