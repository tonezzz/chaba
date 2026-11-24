# Dispatch outcome — rk600-shutter-go-live (attempt 3, 2026-11-24)

## What I did

Attempts 1–2 did the real work but both checkpoints failed to commit
(attempt 1: no commits at all; attempt 2: worktree 63 commits behind,
commit aborted), so merge-sweep counted them as failed and the branch
never landed. This run salvages attempt 2's verified artifacts onto a
fresh branch so the checkpoint can commit cleanly.

1. **Salvaged from `origin/dispatch/20261124-161757-shutter-control-ui-armed-gate-`:**
   - `docs/ssot/jobs/home-assistant/2026-11-24-rk600-shutter-go-live-runbook.yml`
     — verified live-state snapshot + ordered go-live checklist
     (manual smoke → re-enable wind drivers → armed policy decision).
     Already reflects Tony's wind-unit answer applied live.
   - `scripts/home-assistant/dev-shutter-tour.py` — narration strings
     `kn` → `m/s` (matches the live relabel).
   - Deliberately NOT taken: `docs/ssot/kanban/cards/rk600-shutter-go-live.yml`
     (board-api is the write path; the branch copy is stale) and
     `docs/ssot/ssot.runbooks.yml` (master has since renamed
     michael-dev → mn-ha-dev; old branch would regress it).

2. **No live HA mutation this run.** Attempt 2 already applied the
   m/s relabel on michael-ha at 16:34 today and verified it
   (sensor.rk600_wind_speed = 2.88 m/s, helper = 12.0 m/s, drivers
   still disabled, armed still off). michael-ha/home-assistant MCP
   servers are unreachable from tony-omen this session, so no fresh
   re-verification — state assumed unchanged ~3h later.

## Result

Card step 3 (wind-unit) was completed live by attempt 2. Steps 1–2
(manual smoke, re-enable `automation.rk600_shutter_close/open`) remain
physically gated on shutter-motor repair. Steps 4–5 unchanged. Card
correctly stays open/blocked; nothing here should move it.

## How to verify

- Repo: `docs/ssot/jobs/home-assistant/2026-11-24-rk600-shutter-go-live-runbook.yml`
  contains the full live-state snapshot and remaining-step runbook.
- Live (when HA MCP/SSH reachable): `sensor.rk600_wind_speed` unit `m/s`;
  `input_boolean.shutter_control_armed` still `off` until smoke passes.
- Prior attempt outcome:
  `dispatch-outcome-20261124-161757-shutter-control-ui-armed-gate-.md`
  on branch `dispatch/20261124-161757-shutter-control-ui-armed-gate-`.

lessons:
- Dispatch checkpoint aborts when the worktree is far behind
  origin/master — attempt 2 did all the live work then lost it to a
  63-commit-behind commit failure. Salvage pattern: fetch the old
  dispatch branch and `git checkout <branch> -- <paths>` the artifacts
  onto a fresh dispatch branch.
- Do NOT blanket-checkout files from an old dispatch branch — card
  YAML races board-api and master may have moved on (ssot.runbooks.yml
  regressed here); cherry-pick paths, not the branch.
