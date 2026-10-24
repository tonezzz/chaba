# dispatch outcome — jev-model-chain-probe5 (model-chain verify)

## Task
Expected: card `action.lane=free_lane` + `action.model=litellm/gemini-3.5-flash-lite`;
session env `DEVIN_MODEL=flash-lite`. Touch marker + commit.

## Result: FAIL — model chain still broken

Verified live state (not assumptions):

- `GET /cards` -> `jev-model-chain-probe5.action` = `{type: dispatch, status: running,
  runner: tony-macbook}` — **no `lane`, no `model`** persisted at claim.
- `systemctl --user show devin-task-20261025-062616-expected-card-action-lane-free.service
  -p Environment` — **no `DEVIN_MODEL`**; the ExecStart's
  `${DEVIN_MODEL:+--model ...}` expanded to nothing, so devin launched on the
  default model (SWE-2 High), not `litellm/gemini-3.5-flash-lite`.

## Root cause (new surface vs probes 2/3)

The card was claimed by **tony-macbook**, which runs a **pre-patch runner-agent**:
`~/.local/bin/runner-agent` is dated 2026-10-15 and contains no `classify_lane` /
`LANE_MODELS` / `JEV_LANE` code; `runner-agent.service` has no `JEV_LANE` env.
The card brief said the patched fleet was idc02/mn01/omen — but a 4th, unpatched
runner won the claim. No classify ran -> no lane/model persisted -> no
`DISPATCH_MODEL` -> no `DEVIN_MODEL` on the spawned unit.

## Structural fix (already carded)

`dispatch-classify-at-queue-time` (OPS-0838) is still **backlog**. Moving classify
into board-api's `queue` verb puts `action.lane`/`action.model` on the card before
ANY claimer sees it — and even Oct-15 binaries already forward `action.model ->
DISPATCH_MODEL` (line 775). Per-runner patching is whack-a-mole; this is the
claimer-agnostic fix. Evidence comment added to that card.

Side observation: `jev-model-chain-probe4` is concurrently `doing/running` with no
lane/model on its card either — same failure signature.

## Artifacts

- `probe-marker-jev-model-chain-probe5.txt` — committed `1c7503ead` on
  `dispatch/20261025-062616-expected-card-action-lane-free` (no push per rails).
- Board comms posted on `jev-model-chain-probe5` and `dispatch-classify-at-queue-time`.

## How to verify

```bash
git show 1c7503ead:probe-marker-jev-model-chain-probe5.txt
curl -s https://idc03.taila0626a.ts.net:10000/cards | python3 -c \
  "import sys,json; print([c['action'] for c in json.load(sys.stdin)['cards'] if c['id']=='jev-model-chain-probe5'])"
systemctl --user show devin-task-20261025-062616-expected-card-action-lane-free.service -p Environment
```
