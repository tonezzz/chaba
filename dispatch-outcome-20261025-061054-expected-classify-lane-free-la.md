# Outcome — jev-model-chain-probe (20261025-061054-expected-classify-lane-free-la)

**Verdict: chain BROKEN — this session runs the devin default model (SWE-2 High), not `litellm/gemini-3.5-flash-lite`.** The probe found a real gap and the fix is in commit `1577b26d`.

## Evidence (observed live in-session)

- Unit env (`/proc/<systemd-run bash>/environ`): `DEVIN_BIN`, `PERMISSION_MODE`, `PROMPT`, `TASK_DIR` — **no `DEVIN_MODEL`**.
- Devin cmdline: `devin -p --permission-mode dangerous --respect-workspace-trust false --prompt-file ... --export ...` — the `${DEVIN_MODEL:+--model "$DEVIN_MODEL"}` expansion was empty, so **no `--model` flag**.
- Card had no `action.lane`/`action.model`; comms show `idc02` claimed it and `chaba` posted `started devin-task-... on idc02 (dispatch)` — that comm format is `runner-agent.py:1014`, i.e. **runner-agent** claimed, not kanban-dispatch (idc03 + tony-omen deferred on the push guard).

## Root cause

The jev-pilot Phase 2 lane routing (`classify_lane` keyword-first + `LANE_MODELS` free_lane→flash-lite) lived only in `scripts/board/kanban-dispatch.py` behind `JEV_LANE=1`. `scripts/board/runner-agent.py` — the claimer on remote hosts — forwarded only an explicit `action.model`. Unset lane on a runner claim ⇒ no `DISPATCH_MODEL` ⇒ devin default.

## What changed (commit 1577b26d)

- `scripts/board/dispatch_repos.py` — canonical home for `LANE_MODELS`, `LANE_EXECUTORS`, `LANE_KW`, `LANE_COMPARE`, `JEVOS`, `classify_lane` (moved verbatim).
- `scripts/board/kanban-dispatch.py` — local defs replaced by `dr.*` aliases (behavior + import surface unchanged).
- `scripts/board/runner-agent.py` — dispatch claims now resolve the model the same way: explicit `action.model` > explicit `action.lane` via `LANE_MODELS` (unconditional) > `JEV_LANE=1` `dr.classify_lane`. `lane: manual` is never claimed; a classified-manual claim fails loudly.
- `docs/ssot/kanban/ssot.kanban.yml` — `action.lane` documented.
- `docs/ssot/jobs/kanban/2026-10-25-runner-agent-lane-model-chain.yml` — trail.
- `jev-model-chain-probe.marker` — marker deliverable with the evidence.

## Verification

- `py_compile` all three scripts — OK.
- `dr.classify_lane(probe card)` → `free_lane` → `litellm/gemini-3.5-flash-lite` (keyword path, no jevos needed).
- importlib load of kanban-dispatch — aliases resolve, classify works.
- `python3 -m unittest discover -s tests/board` — **186 tests OK (2 skipped)**.

## Remaining gaps (not fixable from this worktree)

1. `JEV_LANE=1` is not in `runner-agent.service` env on idc02 (`RUNNER_CAP=3 RUNNER_LABELS=ssd,always-on,cpu,small RUNNER_API=...` only). Until a runner unit sets it, cards with **unset** lane still launch on the default model on that host — deliberate opt-in since `paid_frontier` spends on a paid model. Cards with an explicit `action.lane: free_lane` now route correctly on any claimer with no env needed.
2. `JEVOS_URL` — idc02's open-jev listens on `100.123.163.11:8777`, not the `127.0.0.1:8017` default (keyword layer covers known lanes regardless).
3. `~/.local/bin/runner-agent` + the runner's `dispatch_repos.py` pickup depends on the host's repo-sync/deploy of this merge.

## How to verify the fix end-to-end

Queue a card with `action: {type: dispatch, lane: free_lane}` (no model): the spawned unit env should show `DEVIN_MODEL=litellm/gemini-3.5-flash-lite` and the devin cmdline `--model litellm/gemini-3.5-flash-lite`. For unset-lane classification, set `JEV_LANE=1` (+`JEVOS_URL=http://100.123.163.11:8777` if jevos fallback is wanted) in the runner-agent unit env first.
