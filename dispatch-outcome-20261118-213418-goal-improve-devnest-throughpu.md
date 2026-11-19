# Dispatch outcome — nest-mgr-v2-actuation (Phase 0)

## What happened

This was a re-dispatch of card `nest-mgr-v2-actuation`. The prior session
(universal-kettledrum, 21:02–21:16) had already implemented Phase 0 and
auto-committed it on `dispatch/20261118-210246-…` (fd8903480a) — the
branch was never merged, so this worktree still had v1. I cherry-picked
the checkpoint clean onto this branch, then reviewed + verified the
implementation against the card spec and closed the remaining gaps
(test, spec doc).

## What changed (branch dispatch/20261118-213418-…)

- `stacks/services/nest-mgr/nest-mgr.py` (+400, from prior checkpoint):
  v2 actuation plane — `monitor|recommend|guarded` resolved per tick from
  `NEST_MGR_MODE` env > `~/.local/share/nest/mode` > monitor; safety flags
  only ever lower the mode. Restart planner: never-list (card-owned,
  unmanaged, nest-mgr self, manual-units, prod lane, Restart=on-success,
  unit circuit) checked BEFORE allowlist (`NEST_RESTART_OK=1` or
  `restart-allowlist`); throttles (≥3 failed ticks, 5 min cooldown,
  ≤2 restarts/h/unit); unit circuit (2 failed restarts/h) + host circuit
  (>5 execs/h → monitor until flag removed); `actuation.off` kill switch
  checked every tick. `actions[]` audit ring (200) in manager-state.json,
  Actuation section on the `nest-<host>` CMS page, `--actions` CLI.
  Guarded path implemented but inert without `actuation.on` opt-in, and
  `--dry-run`/`--report` degrade guarded→recommend so previews can never
  execute.
- `scripts/device-telemetry/agent.py`: mirrors mode / act_1h / circuit /
  last-action into `svc_nest_mgr_*` HA attributes.
- `install.sh` / `verify.sh` / `README.md`: fleet list updated to the six
  deployed hosts (idc02 idc03 con01 mn01 tony-omen tony-dell), v2 runbook
  (modes table, flag files, rollout commands).
- NEW `stacks/services/nest-mgr/test-actuation.py`: 21-check gate-matrix
  test, tempdir-isolated with a fake `systemctl` — added this session.
- NEW `docs/ssot/jobs/devnest/2026-11-18-nest-mgr-v2-actuation.yml`:
  Phase-0 spec — decisions (never-before-allow ordering, flag-file
  control surface, recommend ceiling, pilot hosts), step status,
  deploy gate.

## Result

Phase 0 complete: spec + recommend-mode implementation, zero execution.
21/21 gate-matrix tests PASS on tony-omen. Not deployed — guarded still
requires per-host `actuation.on` plus explicit deploy approval.

## Verify

```bash
python3 stacks/services/nest-mgr/test-actuation.py   # 21/21 PASS
HOME=$(mktemp -d) python3 stacks/services/nest-mgr/nest-mgr.py \
    --once --dry-run                                  # state only, no CMS/systemd
```

When deploy is approved: `./install.sh idc02 con01 mn01` (lands in
monitor), then `ssh <h> 'echo recommend > ~/.local/share/nest/mode'`.
