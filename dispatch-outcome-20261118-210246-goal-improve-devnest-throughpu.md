# nest-mgr-v2-actuation — Phase 0 dispatch outcome

Card: `nest-mgr-v2-actuation` · runner: tony-omen · 2026-11-18

## What changed

**`stacks/services/nest-mgr/nest-mgr.py`** — v1 observer-governor extended
with the v2 gated actuation plane (Phase 0: recommend-mode machinery,
zero execution):

- **Modes** resolved each tick: `NEST_MGR_MODE` env →
  `~/.local/share/nest/mode` file → `monitor` (default, v1 behavior).
  Flag files can only *lower* the effective mode: `actuation.off` kill
  switch and `host-circuit.open` breaker force monitor; `guarded`
  requires the per-host opt-in `actuation.on` else degrades to
  recommend.
- **Restart planner**: per-unit `fail_ticks` tracked in state; a unit
  failed ≥3 consecutive ticks is evaluated against the never-list
  (card-owned, `NEST_OWNER=none/unmanaged`, nest-mgr itself,
  `manual-units` file, topology `prod` lanes — `NEST_MGR_PROD_OK=1`
  override, `Restart=on-success`, open unit circuit) then the allowlist
  (`NEST_RESTART_OK=1` on unit env/file/drop-ins or `restart-allowlist`
  file), then cooldown/rate limits (5 min cooldown, ≤2/hour/unit).
  `Restart=` is now captured in discovery (`systemctl show -p Restart`).
- **Guarded path** is implemented (`systemctl --user restart` only) but
  inert: unreachable without mode=guarded + `actuation.on` + allowlist +
  all conditions — Phase-1's flip is pure config, no code change.
- **Circuit breakers**: 2 failed restarts/hour → `circuit/<unit>.open`
  flag + event; >5 executed restarts/hour → `host-circuit.open` + mode
  drops to monitor; `rm` the flag to reset.
- **Audit**: every event — recommended, held (names the blocking gate,
  re-emitted hourly/on-change), executed, circuit-open, mode-change —
  appends `{ts,host,unit,prior_state,action,reason,outcome}` to
  `manager-state.json` `actions[]` (ring, 200). Fingerprint covers
  actuation posture + audit tail so events republish the CMS page
  immediately.
- **CMS page**: `nest-<host>` gains an Actuation section (mode +
  requested, flag posture, lifetime metrics, last 8 audit rows) and
  `✅restart-ok` markers on opted-in units. New `--actions` CLI prints
  the audit tail. `NEST_STATE_DIR` env override added for testing.

**`scripts/device-telemetry/agent.py`** — `services["nest-mgr"]` now
carries `mode`, `act_1h`, `circuit`, `last` → telemetry-ha-push.py turns
them into `sensor.<dev>_svc_nest_mgr_{mode,act_1h,circuit,last}`
automatically; no HA-side change.

**`install.sh`/`verify.sh`/`README.md`** — default host list updated to
the deployed fleet (idc02 idc03 con01 mn01 tony-omen tony-dell); README
documents modes, flag files, restart policy, and Phase-0 rollout
commands. verify.sh shows mode + action count.

**`tests/nest_mgr/test_nest_mgr_v2.py`** — 27 unit tests: mode
resolution, never-list-beats-allowlist ordering, throttle, recommend
dedupe/held, guarded exec + unit/host circuits, plan_only-never-executes.

**`docs/ssot/jobs/nest/2026-11-18-nest-mgr-v2-actuation.yml`** — spec +
runbook for the mechanism (flags, gates, circuits, audit, rollout).

## Verification

- 27/27 new tests pass; `py_compile` clean on both edited py files;
  `bash -n` clean on install/verify.
- `--discover` on tony-omen: 11 nodes, census unchanged.
- `--report` renders the Actuation section; `--once --dry-run` writes
  `manager-state.json` (`manager: nest-mgr v2`, actuation block,
  actions[]) with zero CMS writes.
- Seeded `fail_ticks=2` + synthetic failed node in recommend mode →
  `{action: restart, outcome: recommended}` event, no systemctl call.
- device-telemetry `_services()` reads the v2 state and yields
  `mode=recommend, act_1h=1, circuit=closed, last="mode-change -
  recommend"`.

## Not done / handoff

- **No deploy** — dispatch constraints; nothing installed anywhere.
  Rollout: merge → `./install.sh idc02 con01 mn01` (lands monitor) →
  `ssh <h> 'echo recommend > ~/.local/share/nest/mode'` per pilot host.
- Work-stealing planner (Phase 2) is a documented plug point only —
  needs broker-normalized package + MDDB lease store, gated on restart
  pilot metrics.
- Success metrics (restart success rate etc.) accumulate in
  `actuation.metrics` once pilots run; 7-day before/after compare is a
  Phase-1 evaluation task.

## Files touched

`stacks/services/nest-mgr/{nest-mgr.py,install.sh,verify.sh,README.md}` ·
`scripts/device-telemetry/agent.py` · `tests/nest_mgr/` (new) ·
`docs/ssot/jobs/nest/2026-11-18-nest-mgr-v2-actuation.yml` (new)
