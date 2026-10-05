# dispatch outcome — ada_enroll_speaker "not enough audio buffered"

## Finding

The frontend capture path is **not** the failure. Proof: the tongue-
twister turn the user spoke ("ชาวฟาผัดฟักเย็นฟาผัดฟักผัด…") reached the
backend and was transcribed correctly by Gemini — it's in
`scripts/jev/train-all.jsonl` (line 1513, mined 2026-10-03). Real audio
streams; the *enrollment buffer* is what stays empty.

Buffering is server-side (ada-pi `SpeakerSession._recent` /
`_pending_voice` → `enroll_from_buffer`), outside this worktree. The
prime suspect is the **TTS-echo feed gate** (ada-pi commit bc06168,
deployed 2026-10-03 — after the 09-28 enrollment fix passed its live
benchmark): `pwa_server` now skips `speaker_session.feed()` while
`provider._response_active` + 0.6 s tail. If the user answers Ada's
"speak now" prompt inside that window — or if `_response_active` latches
after one of the recurring Gemini 1008 mid-response aborts — every enroll
attempt reports "not enough audio buffered" while conversation keeps
working. Full analysis + ranked candidates in
`docs/ssot/jobs/ada/2026-10-05-ada-enroll-speaker-buffer.yml`.

## What changed (this worktree)

- `stacks/tony-dell/tony-ha/www/ada-voice-card.js` — `_handleControl` now
  surfaces the speaker ws events the card previously dropped:
  `speaker`, `speaker_unrecognized`, `speaker_enrolled`,
  `identity_changed`, plus a generic `enroll_result` diagnostic slot.
  They render on the status line and the ada-activity-card feed — the
  next failure will show whether the server identified/fed/enrolled
  instead of looking like "audio wasn't captured". `node --check` OK.

## Recommended ada-pi fix (needs a dispatch with ada-pi access)

1. Narrow the gate: keep appending fed audio to `_recent` during
   `_response_active`; gate only identify/auto_learn/`_pending_voice`.
   (The echo incident was about *identifying* Ada's voice, not
   buffering.)
2. Reset `_response_active` on provider reconnect/abort so the gate
   can't latch.
3. Emit `{type:"enroll_result", ok, fed_s, voiced_s}` on enroll attempts
   — the card now renders it.
4. Re-run `tests/scenarios-live/speaker_enrollment.yaml` on idc01 to
   confirm.

## Verify

- Card change: `node --check` passes; speaker events appear in the Live
  activity feed on the next session.
- Root cause: on idc01, `journalctl -u ada-ha-tony | grep -E 'enroll|
  response_active|voiced'` across a failed attempt shows whether feed()
  was gated vs fed-but-unvoiced.

## Notes

- No commit/push/deploy performed beyond this worktree branch, per
  dispatch rules. ada-pi could not be edited (outside worktree).
- Prior dispatches of this task (20260928-081016, 20261005-122613)
  exited with zero output; this run produced the analysis + the
  chaba-side half of the fix.
