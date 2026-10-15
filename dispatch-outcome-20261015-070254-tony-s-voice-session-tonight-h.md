# Dispatch outcome — ada-cast-wrong-target-verbose-loop (ADA-0684)

## What was found (transcript 2026-10-14-4029a6447f, 23:20–23:26 ICT)

- Tony asked (Thai) to send God's Eye View to "the TV". Ada called
  `cast_to_screen(screen=1, shortcut='gev')` twice — wrong tool family
  entirely ('TV' = `tv_action`/`media_player.tony_tv`, never a numbered
  vcast display). Both `/pub` acks returned `ok: true, delivered: 0`
  (screen 1 offline) — a phantom success she narrated as "opened on
  screen 1".
- `control_entity(media_player.tony_tv, turn_on)` returned `ok: true`
  on an entity HA itself reported `unavailable` (restored via plug) —
  the MED-0493 phantom-state pattern, unfixed in code.
- The correction "not screen 1 — the TV" was **inverted** into an
  `ada_remember` write ("user wants only screen 1") that the confirm
  gate refused — while she claimed she'd remembered it (OPS-0567:
  correction dies at the gate, phantom claim survives).
- `tv_action` was only attempted on attempt ~5 and correctly failed
  (`cast_verify` + `tv_input` both `unavailable`, `ok: false`).
- No breaker covered the goal loop: the existing storm breaker keys on
  tool+error-class, so a failure wandering `cast_to_screen →
  control_entity → tv_action` never trips it; `ok:true delivered:0`
  results don't even count as failures.
- Tony's frustrated short turns DID collapse her verbosity — the
  register-mirroring worked, it just had no budget rule until profanity
  arrived.

## What changed — integrations/ada-voice/ Drop 10 (staged, NOT deployed)

Six patches + one scenario against ada-voice `main@5dc7665`:

- `backend/screens.delivered-zero.patch` — `cast_to_screen` /pub results
  with `ok:true delivered:0` flip to `ok:false` ("screen N is not
  connected — never claim it showed"); now counts toward breakers.
- `backend/ha.unavailable-precheck.patch` — `control_entity` refuses
  up-front when precheck state is `unavailable`.
- `backend/tool_runner.goal-loop.patch` + `common.goal-loop.patch` —
  cross-tool `_goal_loop`: `GOAL_LOOP_ASK` (default 2) consecutive
  actuating failures in one session attach `stop_and_ask` ("tell the
  user ONE short sentence and ask"). Clean/`needs_confirm` results
  clear the streak; directive not hard-block (explicit 'try again'
  stays legal); per-tool storm breaker remains the hard floor.
- `backend/tool_guide.target-fidelity.patch` — 'the TV'/ทีวี →
  `tv_action`, never a numbered screen even as fallback; corrections
  binding.
- `backend/realtime_provider.cast-loop.patch` — TARGET FIDELITY
  (corrections re-issue to the named target; never store inverted),
  FRUSTRATION BUDGET (short/repeated/corrective turns → one clause,
  no offers/questions; brevity never requires rudeness), FAILED-ACTION
  LOOP (two failures end initiative; `stop_and_ask` binding).
- `tests/scenarios/cast_wrong_target_loop.yaml` — replays the incident.
- `tests/ada/test_cast_loop_breaker.py` — chaba-side gate: clones
  ada-voice, applies all six patches, runs the scenario.

## Verification

- /tmp clone + patches: `pytest tests/` — **1467 passed, 1 skipped**;
  scenario suite 20/20 incl. new; `tool-lint` clean (54 declared).
- Scenario trace: delivered:0 fails loudly → unavailable refuses →
  `stop_and_ask` on 2nd cross-tool failure → corrected `tv_action`
  resolves `ok:true` in one retry → 3rd same-tool repeat hits
  `circuit_open` (deterministic 'max 2 attempts then ask' floor).
- `git apply --check` all six clean on fresh clone of `5dc7665`.

## Result / next

Staged + verified only — **not deployed, not pushed** (rails + ada-voice
deploy policy; idc03 is deploy-only). Deploy path: apply drop 10 at the
tony-dell edit point per `integrations/ada-voice/README.md`, gates are
already in deploy-ada.sh, then restart ada-ha-* units — needs Tony's
explicit approval.
