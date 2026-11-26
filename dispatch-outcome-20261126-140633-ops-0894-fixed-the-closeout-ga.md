# dispatch-zero-commit-sessions-epidemic — investigation outcome

## Root cause (found + verified)

The zero-commit dispatch epidemic was **not** thin prompts, dead model
lanes, or broken worktrees. It was a model-namespace leak in the
claim→launch path, fixed 2026-11-24 (devin-executor-model-routing,
DEV-0958) and already deployed fleet-wide.

Chain: pre-fix `runner-agent` claim-time `classify_lane()` persisted
`action.model = LANE_MODELS[lane]` — a `litellm/*` proxy alias — and set
`DISPATCH_MODEL` to it executor-blind. `devin-dispatch` passed it to
`devin -p --model litellm/...`, which the devin CLI rejects:
`Error: Unknown model` → exit 1 in <1-3s → `exit_code=1`, no
sessions.db row, no transcript.json, no commits, branch head == base.

Only cards that were lane-classified AND fell through to the devin path
(no opencode profile resolution) AND lacked a valid `action.model` died —
hence the coin-flip appearance across hosts/lanes.

## Evidence

- Reproduced live on mn01: `devin -p --model litellm/gemini-3.5-flash-lite`
  → `Error: Unknown model` + Available list, immediate exit.
- Smoking gun in card comms: finish tail `.6, deepseek-v4-pro` is the end
  of devin's "Available:" model list (`...swe-1.6, deepseek-v4-pro`) —
  i.e. the unit journal contains the Unknown-model error output.
- Session signature verified on mn01 + tony-macbook + idc02 task dirs:
  exit_code=1, no transcript, no sessions.db row; devin parent log ends
  at `run_repl_mode: close`, before model resolution/ACP spawn.
- tony-macbook: ~20 such failures Oct 26-27 incl. both OPS-0894
  investigation dispatches; ZERO since 2026-11-25.

## Secondary bug (also already fixed)

"Finished with result 'exit-code' recorded 'finished (ok)'": old
`collect()` read `ExecMainStatus=0/Result=success` DEFAULTS from
--collect'ed units. Current code reads task-dir `exit_code` first, unit
fields only while loaded, then journal; unproven exits report not-ok.

## Current state — fix is live

- `dispatch_repos`/`runner-agent`/`kanban-dispatch`: executor-aware
  `lane_model()` split — litellm ids only for opencode,
  `DEVIN_LANE_MODELS` (swe-2-flash-medium; paid_frontier unpicked) for
  devin; `model_valid_for_executor` drops foreign ids with a comms note.
- `devin-dispatch._model_preflight` refuses unknown ids BEFORE
  systemd-run; `claude-dispatch` self-validates.
- Fleet verified: installed runner-agent md5 == repo on mn01, idc02,
  idc03, tony-dell, tony-macbook, tony-omen; devin-dispatch has
  preflight on all six. con01 unreachable from mn01 (ssh denied) —
  unverified, worth a glance.
- Regression tests exist: tests/board/test_runner_agent_lane.py,
  tests/devin/test_model_preflight.py.
- 39 cards still carry persisted `action.model: litellm/*` — safe under
  current guards (dropped for devin claims, correct for opencode).

## Deliverables

- `docs/ssot/jobs/kanban/2026-11-26-dispatch-zero-commit-litellm-model-leak.yml`
  — full investigation trail (signature, evidence, verification).

## How to verify

- `devin -p --model litellm/x` → "Error: Unknown model" (expected reject).
- `python3 -m pytest tests/board/test_runner_agent_lane.py tests/devin/test_model_preflight.py`
  on a host with pytest.
- Fleet: `md5sum ~/.local/bin/runner-agent` vs repo file on each runner.

lessons:
- lane->model picks must be executor-namespaced at BOTH claimers; a litellm/* id on `devin --model` is a sub-second 'Unknown model' death with zero commits
- dispatch failure signature: exit_code=1 + no transcript.json + no sessions.db row + devin log ending at run_repl_mode close
- unit journal tail '.6, deepseek-v4-pro' was the tail of devin's Available-models list — journal fragments of 'Error: Unknown model' output are the tell
- --collect'ed systemd units report ExecMainStatus=0/Result=success DEFAULTS — exit evidence must come from the task-dir exit_code file first
