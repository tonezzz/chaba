# Dispatch outcome — speaker-id-owner-rebind

Card: `docs/ssot/kanban/cards/speaker-id-owner-rebind.yml`
Incident: session `7a74536b32` (2026-10-07) — Tony's own session was
labeled 'KK' (two ~64% hits) and every owner-gated tool refused him.

## Where the work lives

Runtime code is in ada-pi, not chaba. Worktree:
`~/CascadeProjects/ada-wt-speaker-id-owner-rebind`,
branch `dispatch/20261010-080914-speaker-id-owner-rebind`
(base `0aa544f`). **Not committed, not pushed, not deployed** — per the
task rails. The chaba worktree carries the job trail
(`docs/ssot/jobs/ada/2026-10-10-speaker-id-owner-rebind.yml`) and this
outcome file.

## What changed (ada-pi)

- `backend/speaker_id.py` — `NON_OWNER_MIN_CONF` floor
  (`ADA_SPEAKER_NON_OWNER_MIN_CONF`, default 0.70): a new non-owner
  person hit below the floor never accrues toward a label — treated as
  a miss (audio still banks for enrollment). Owner + media labels and
  already-established labels are exempt. Would have stopped the
  incident (two 64% hits). New `SpeakerSession.correct_speaker(claimed)`:
  re-scores the trailing `_recent` buffer — keeps the label only if the
  buffer still verifies it at threshold; else rebinds to another
  verified person, reclaims the owner when the owner's print is the
  buffer best at >= `OWNER_RECLAIM_MIN` (0.25), binds an explicit claim
  only when the buffer's best match agrees, and clears to unrecognized
  otherwise. Media hits never bind. Fires `on_identified`/`on_cleared`.
- `backend/tool_runner/__init__.py` — `_reverify_secondary_turn()`:
  before any owner-only denial fires, re-score the buffered voice; a
  label the audio can't reproduce is dropped/rebound (heals the per-call
  contextvar and the shared speaker field, logs
  `speaker_label_reverted`). Fails closed on error/no session.
- `backend/realtime_provider.py` — the provider-dispatched secondary
  gate (which bypasses the runner gate) calls the same re-verify; plus
  instructions telling Ada to call `speaker_profiles action='correct'`
  on "I'm not KK" / "this is Tony" — never just apologize while the
  label stays pinned.
- `pwa_server.py` — `_on_speaker_cleared` callback: clears provider +
  tool_runner speaker fields, restores `conversation.speaker_identity`
  to the caller, emits a `speaker_cleared` ws event, injects a system
  turn telling Ada to treat the speaker as unrecognized.
- `backend/tools.d/speaker_profiles.py` — `action='correct'` (already
  `secondary_allowed` — the mislabeled guest is the caller who needs
  it; it mutates no profile). Optional `name=` carries the claim.

## Tests

- `tests/test_speaker_id.py` — `NonOwnerFloorTest` (6) +
  `CorrectSpeakerTest` (9). Existing hysteresis tests' guest scores
  bumped above the floor so they keep testing streaks, not the floor.
- `tests/test_memory_banks.py` — 5 deny-path re-verify cases (cleared
  label proceeds + heals shared field; owner rebind; verified label
  still denies; reverify exception fails closed; no session stays
  denied).
- `tests/test_speaker_profiles_tool.py` — `CorrectActionTest` (7).
- `tests/scenarios/speaker_id_correction.yaml` + `speaker:` step in
  `scenario_engine.py` (`_StubSpeakerSession` with scripted verdicts).

## Verification

```
cd ~/CascadeProjects/ada-wt-speaker-id-owner-rebind
~/CascadeProjects/ada-pi/.venv/bin/python -m pytest tests/ -q
# 1010 passed, 1 skipped, 1 failed
```

The one failure is `test_tool_audit.py::LintAgainstRepoTests` —
pre-existing baseline lint debt (voice_fx descsize, `yt_cached_list`
impl, voice_fx coverage); confirmed failing on the clean tree via
`git stash`. Host python lacks `google-genai`; use the ada-pi checkout
venv as above.

## Security posture

Unlabeled voices keep owner rights (same fail-open posture as the
stale-label expiry), so clearing a disputed label loses nothing; a
buffer still verifying the guest label keeps denying; a false identity
claim can't bind without matching audio; reverify errors fail closed.
Nothing here lets a secondary speaker widen access.

## Not done (deliberately)

- No commit/push/deploy — card rails and ada-pi deploy flow
  (idc03 deploy-only, `deploy-ada.sh` promotion) both require explicit
  approval.
- Residual gap: if the buffer genuinely verifies the disputed label
  (real guest still talking), it stands — the model is told to suggest
  speaking longer and correcting again.
