# dispatch-outcome: jev-model-chain-probe6 (OPS-0842)

**Verdict: FAIL — new failure surface.** The fleet deploy did its job
(mn01's runner-agent is the patched build, mtime Oct 24 23:25), but the
model chain broke at a new step: **claim-time classify ran and returned
`manual`**, so no lane/model was ever assigned.

## Evidence collected this session

- Live card `action`: `{type: dispatch, status: running, runner: mn01}`
  — no `lane`, no `model` persisted.
- Unit env (`systemctl --user show devin-task-...-service Environment`):
  no `DEVIN_MODEL`, no `DISPATCH_MODEL`.
- devin cmdline: no `--model` flag → session runs the devin default
  (SWE-2 High), not `litellm/gemini-3.5-flash-lite`.
- `dispatch_repos.classify_lane(card)` run live → returns **`manual`**:
  `LANE_KW['manual']` contains bare substring `"macbook"`, which fires on
  the probe brief's host list `"macbook+idc03+dell just synced"`. The
  manual check runs before all other lanes, so free_lane's `"probe"`
  keyword never gets a chance.

## Secondary defect found

`~/.config/systemd/user/runner-agent.service.d/jev-lane.conf` on mn01 is
malformed: line 1 is `Environment=JEV_LANE=1` with **no `[Service]`
header** — systemd logs "Assignment outside of section. Ignoring." and
the runner-agent unit env has no JEV_LANE. Side-effect: it actually let
this probe run — with JEV_LANE live, the env-path classify would also
have returned `manual` and refused the card outright.

## Still-open gaps from earlier probes

- Claim-time classify only mutates the in-memory action after the claim
  POST; nothing PATCHes lane/model back to the card (probe4 finding).
- Queue-time classify in board-api (`dispatch-classify-at-queue-time`,
  OPS-0838) remains the durable fix — and would also give a single place
  to persist the verdict.

## Recommendations (not implemented — probe task was observe+mark)

1. Narrow `manual` keywords — `"macbook"` matches any host-fleet
   mention; use word-boundary/context phrases ("blocked on tony" style)
   or require multiple manual signals.
2. A `manual` classify verdict should be persisted/logged to the card so
   a silently-never-claimed card is visible on the board.
3. Fix `jev-lane.conf` drop-in on mn01 (add `[Service]` header) — and
   audit other runners for the same malformed drop-in.
4. Probe briefs should avoid runner hostnames until the keyword table is
   fixed.

## Artifacts

- `probe-marker-jev-model-chain-probe6.txt` — committed marker
- This file. No code changes; no push (per dispatch rules).
