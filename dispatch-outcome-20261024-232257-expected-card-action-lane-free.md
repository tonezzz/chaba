# Dispatch outcome — jev-model-chain-probe4 (mn01)

## Verdict: FAIL — model chain still broken, but at a new point

Expected: card `action.lane=free_lane` + `action.model=litellm/gemini-3.5-flash-lite`,
session env `DEVIN_MODEL` set. Observed: none of the three.

- Live card (`GET /cards`): `action={type:dispatch, status:running, runner:mn01}` — no lane/model.
- Unit `Environment=` (`systemctl --user show`): no `DEVIN_MODEL` → `devin` launched
  with no `--model` flag → session runs the default model (SWE-2 High), not flash-lite.

## Root cause

mn01 claimed the card at 23:22:59Z with a **stale runner-agent**:

- `~/CascadeProjects/chaba` on mn01 sits at `5f2fabfd` (05:51 ICT), **91 commits
  behind origin/master**. The lane-routing fix `1577b26d` ("runner-agent: lane ->
  DISPATCH_MODEL routing", 06:16:59 ICT / 23:16:59Z) is absent.
- The installed `~/.local/bin/runner-agent` (Oct 22 03:12, md5-identical to the
  checkout copy) only passes an explicit `action.model` — it never classifies, so
  `DISPATCH_MODEL` was never set for `devin-dispatch.sh`.
- The claim fell inside the hourly `chaba-repo-sync.timer` lag window: fix merged
  ~6 min before the claim; mn01's next sync was ~30 min away.

## Secondary gap (still in the fixed code)

`runner-agent.start_task()` sets `a["lane"]`/`a["model"]` on the in-memory card
**after** the claim POST (`runner-agent.py:1080-1083`) and never writes them back —
only `DISPATCH_MODEL` reaches the child env. So even with fresh code, remote
claimers would run the right model but the card still wouldn't show
`action.lane`/`action.model`. Persist needs a write-back: classify inside
board-api's `queue` verb (probe2's recommendation — this base's `board-api.py`
has no classify call there), or a claim/patch body that carries lane+model.

## What changed

- `probe-marker-jev-model-chain-probe4.txt` — probe evidence + verdict (committed).
- This outcome file.
- Posted result to the card via board-api `/comment`.

## How to verify

- `git show HEAD --stat` on this branch: marker + outcome.
- `curl -s https://idc03.taila0626a.ts.net:10000/cards | jq '.cards[] | select(.id=="jev-model-chain-probe4")'` — action lacks lane/model; comms carry the finding.
- `systemctl --user show devin-task-20261024-232257-expected-card-action-lane-free -p Environment` — no DEVIN_MODEL.

## Suggested follow-ups (for the next probe / fix card)

1. Force or wait for `chaba-repo-sync` on mn01, then re-run the probe — expect
   session env to pass but card fields to still be absent (secondary gap).
2. Implement classify-at-queue in board-api `do_action("queue")` so lane/model
   land on the card before any claimer sees it — the design probe2 specified.
3. Consider runner-agent self-update: oneshot could fetch+reset the exec
   checkout before claiming (or refuse to claim when >N commits behind).
