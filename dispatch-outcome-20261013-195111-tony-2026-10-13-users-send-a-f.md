# Dispatch outcome — line-voice-enroll-recognize (2026-10-13)

## What changed

Built file-input speaker ID for Ada LINE lanes (ada-pi only, staged as
drop-in patches — nothing pushed or deployed):

- `integrations/ada-pi/backend/speaker_id.file-input.patch` —
  `decode_audio_file()` (PyAV → PCM16 mono 16k, ffmpeg-CLI fallback,
  `ADA_SPEAKER_FILE_MAX_S` cap), `embed_file(path)`,
  `match_file(path)` → `{match, score, all_scores, best, ha_person…}`
  reusing the same 0.45 threshold + 0.05 margin + media-pool scoring,
  `enroll_from_file(path, name, person)` with the same
  EnrollConflict/own-voice guards as live `enroll()`.
- `integrations/ada-pi/backend/line_relay.voice-enroll-recognize.patch` —
  every archived LINE clip is matched; the persona turn carries
  `[voice: speaker=<name|unknown> score=0.xx person=…]`; unknown voice
  on a caller-mapped lane arms enroll-on-clips
  (`LINE_VOICE_ENROLL_CLIPS=3`, TTL 900s): each clip = one print bound
  to the caller's `person.*`, completing with `enrolled <name>, 3
  prints`. Recognized clip or EnrollConflict disarms cleanly.
- `integrations/ada-pi/backend/speaker_profiles.file-actions.patch` —
  tool gains `action='match_file'` (read-tier) and
  `action='enroll_file'` (mutating, `_may_mutate` gate).
- `integrations/ada-pi/backend/tool_runner.boss-rule.patch` —
  `_speaker_is_owner_tier()`: a fresh positively-identified speaker with
  `{full: true}` person policy (person.tony per persons.yml `role:
  admin`) keeps owner-tier on any member lane; stale labels never
  elevate.
- `integrations/ada-pi/backend/tool_guide.speaker-profiles-file.patch` —
  documents the file actions, threshold/margin, boss rule, and the
  spoofing caveat (voiceprint = evidence, not authentication).
- `integrations/ada-pi/backend/test_line_relay_group.voice-ack.patch` —
  updated saved-clip ack expectation to the new enroll offer.
- `integrations/ada-pi/tests/test_speaker_file_input.py` — NEW, 30
  tests.
- `integrations/ada-pi/README.md` — Drop 5 section (files, install
  runbook, contract, residuals).
- `docs/ssot/jobs/ada/2026-10-13-line-voice-enroll-recognize.yml` — job
  lifecycle doc.

## Result

All work done and verified on `.cache/ada-pi-verify` (clean copy of the
idc03 production checkout): **tool-lint clean** (51 declared tools) and
**1360 pytest tests + 31 subtests pass** (30 new tests covering decode,
file match/enroll roundtrip, relay arm→enroll→confirm flow, tool
actions, boss-rule elevation/stale/fail-closed). All 6 patches dry-run
clean against the pristine idc03 files. Real LINE corpus m4a decode
verified on idc03 (`av` 15.1.0, no system ffmpeg needed). Board comment
posted.

## How to verify / land

1. On tony-dell: `cd ~/CascadeProjects/ada-pi` and apply the six patches
   from `<chaba>/integrations/ada-pi/backend/*.patch` per the Drop 5
   runbook, plus copy `tests/test_speaker_file_input.py`.
2. Deploy via `~/.local/bin/deploy-ada.sh` (runs tool-lint + pytest
   gates itself); restart covers `ada-line-relay`.
3. Live: send a KK voice clip → relay log shows
   `[voice: speaker=KK score>0.45]` on the persona turn.
4. Live: unknown member sends 3 clips → `enrolled <name>, 3 prints`
   ack; a 4th clip matches.

Residuals noted in the job doc: pre-existing live-mic profiles score
below threshold on LINE m4a clips (channel codec) — resolved by
enrolling from LINE clips, which is what the new flow bootstraps; TG
relay not wired (card scoped LINE).
