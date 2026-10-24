# dispatch-outcome: jev-model-chain-probe2 (OPS-0837)

Task: verify the free-lane model chain end-to-end — `classify_lane -> free_lane ->
action.model=litellm/gemini-3.5-flash-lite -> runner session DEVIN_MODEL=flash-lite` —
then touch a marker file and commit.

## Result: FAIL (chain still broken, new root cause found)

| Expected link | Observed |
|---|---|
| card classified to free_lane | `action.lane` absent on live card |
| `action.model=litellm/gemini-3.5-flash-lite` persisted | `action` = `{type, status, runner}` only — no `model` |
| runner unit `DEVIN_MODEL` set | systemd unit `Environment=` has no `DEVIN_MODEL` (verified via `systemctl --user cat devin-task-20261025-061358-expected-classify-lane-free-la`) |
| `devin --model flash-lite` | flag never passed — session runs the devin **default** model |

## Root cause

Fix `c4fc7cac` persists `action.lane`/`action.model` — but only inside
`kanban-dispatch.py start_pending()` (phase B of idc03's own dispatch path).

This card was **claimed by idc02's runner-agent at 06:13**, one minute after
queueing, via board-api `POST /action {do:claim}` (atomic first-wins).
Timeline from card comms: queued 06:13 → idc02 claimed 06:13 → session
started 06:14. idc03's kanban-dispatch never ran `start_pending` on it — it
can't anyway for chaba cards (push guard defer, no `push:chaba` label on
idc03).

`runner-agent.py` never classifies: its dispatch path only reads `a["model"]`
(line ~885). `classify_lane` exists only in `kanban-dispatch.py`. `board-api`
`do_action queue` sets `status=queued` with no classification.

So the claim race means remote-claimed cards bypass classify entirely — the
fix only covers cards kanban-dispatch starts itself.

## Recommended fix (carded as follow-up)

Classify at **queue time**, not start time: `board-api.py do_action("queue")`
should run `classify_lane` and persist `action.lane` + `action.model` before the
card becomes claimable. That is the single mutation door every claimer
(remote runner-agents AND kanban-dispatch) already reads. Alternative:
runner-agent classifies at claim time — duplicates logic and still races.

## What changed

- `probe-marker-jev-model-chain-probe2.txt` — marker file with probe verdict,
  committed as `be9da311` on `dispatch/20261025-061358-expected-classify-lane-free-la`.

## How to verify

- `git log --oneline -1` in this worktree → `be9da311 probe: ... marker`
- `systemctl --user cat devin-task-20261025-061358-expected-classify-lane-free-la | grep DEVIN_MODEL` → no match (the bug)
- Live card `jev-model-chain-probe2` via board-api `/cards` → `action` has no `lane`/`model`
- After the queue-time fix lands: re-run a probe card; expect `action.model`
  on the card AND `DEVIN_MODEL` in the unit Environment AND `--model` in ExecStart.
