# Dispatch outcome — runner-agent-opencode-lane-profile-bug

## What the card asked

`start_task` called `start_opencode_lane(card, "", unit)` for declared
`executor=opencode`, so the card's own `action.lane` never reached the
`lane -> LANE_PROFILES` map — `executor=opencode + lane=free_lane`
failed `no task profile for lane (none)` unless it also pinned
`action.agent_profile`. Spec allowed either forwarding the lane or a
tighter error; related note asked that runner-fleet-health flag
binary/repo drift.

## What I found

- **Start-side fix already merged.** `start_task` now forwards
  `str(a.get("lane") or "")` into `start_opencode_lane`
  (`scripts/board/runner-agent.py:3953`, OPS-1021 / cline-ready-mirror
  9316bb32a, merged before this dispatch). The error already names
  `action.agent_profile or a mapped lane`.
- **runner-fleet-health drift flagging already exists.** `judge()`
  compares each host's installed `~/.local/bin/runner-agent` sha against
  the repo refsha AND the `origin/master` tool pins; wired into
  `scripts/ada/kanban-sync.sh`. The card's comms trail of "installed
  runner-agent drifted" defers is runner-agent's own
  `self_stale_reason` claim gate — a second, independent mechanism.
- **Real remaining gap (fixed here):** the claim gate did not replicate
  start-time routing. `_claimable` for `ex == "opencode"` checked
  OPENCODE_LANES + binary + lane_envelope but never profile resolution,
  so an `executor=opencode` card with a staged envelope but no
  `agent_profile` and an unmapped/absent lane was claimed and then
  failed at start — `finish ok=False` + `retry_record_failure` burned
  the attempt budget. This is exactly how `ops-1244d-janitor-merge`
  died on `no task profile for lane paid_frontier`.
- **Pre-existing red on base:** checkpoint `9b34c16b92f` (Jev
  stagnation gate) changed `runner-agent.py` without bumping its
  `runner-tooling.manifest.json` pin — `test_pin_hashes_match_sources`
  was failing and `sync-runner-tools.sh` would refuse the deploy
  fleet-wide (the same stale-binary class as idc02's Oct-25 copy).

## What changed

- `scripts/board/runner-agent.py`
  - `_claimable` (`ex == "opencode"` branch): after the lane_envelope
    hold, added a profile-resolution hold —
    `card_profile(card) or LANE_PROFILES.get(action.lane)` must
    resolve, else unclaimable with a reason. Explicit executor never
    re-classifies, so the claim-time lane is exactly what `start_task`
    forwards — the check is exact.
  - `executor_defer_reason`: mirrored the hold so it surfaces as a
    debounced board defer naming `agent_profile`, the lane, and that
    no attempt is burned.
- `tests/board/test_executor_contract.py`: +4 hold-class tests
  (mapped `free_lane` without profile claims; `paid_frontier` and
  absent lane held; `action.profile` alias claims) and added
  `agent_profile` to `test_opencode_executor_needs_push_too` so it
  still exercises the push guard past the new hold.
- `scripts/devin/runner-tooling.manifest.json`: `runner_agent`
  sha256 bumped to the new source hash — heals both this change and
  the checkpoint's unpinned edit.
- `docs/ssot/jobs/board/2026-11-24-opencode-lane-profile-claim-gate.yml`:
  job trail.

## Verification

- `tests/board/test_executor_contract.py` — 112 passed (was the card's
  named suite; includes the OPS-1021 lane-forwarding regression).
- `tests/board/test_runner_tooling_contract.py` — 7 passed (was
  1 failed on base before the pin bump).
- `test_runner_agent_lane` + `test_runner_agent_gate` +
  `test_runner_agent_reconcile` + `test_runner_stale_worktree` —
  58 passed.
- `test_runner_agent_launchd` + `test_waiting_cards` +
  `test_stalled_claim_lifecycle` — 100 passed.

## How to verify live

After merge + a `chaba-repo-sync`/`sync-runner-tools` tick on a runner:
`sha256sum ~/.local/bin/runner-agent` should equal the manifest pin;
`runner-fleet-health` stays green. A card with `executor=opencode` +
staged envelope + unmapped lane now shows a defer comms naming
`agent_profile` instead of failing `start failed: no task profile`.

lessons:
- runner-agent.py claim-time gates must replicate start-time routing
  (lane->profile->envelope) or the card fails AFTER claim and the
  attempt ledger pays for it — this card's KNOWN_PITFALL, now closed
  for the profile leg.
- Dispatch checkpoint commits can merge runner-agent.py changes
  without the manifest pin bump — test_runner_tooling_contract catches
  it, but only if someone runs the suite; the fleet then refuses the
  deploy via sync-runner-tools.sh.
- For explicit executor=opencode, action.lane is never re-classified —
  claim gate and start_task read the identical value, so claim-time
  profile resolution is exact, not heuristic.
