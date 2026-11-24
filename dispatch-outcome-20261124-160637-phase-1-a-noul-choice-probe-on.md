# Dispatch outcome — jev-stagnation-gate-for-agent-bench-loop-a70f74

Card: BEN-0824 — "Jev stagnation gate for agent/bench loops". Phase 1
probe + Phase 2 runner/bench wiring + replay of the 4.4h colibri
stall. All delivered in this worktree (no push, no deploy).

## What changed

- **`scripts/jev/loop-gate.py`** (new) — the probe. Per sample it asks
  Jev two questions on the `/v1/systemone` wire shape: noul "is this
  trajectory semantically stagnant" -> p, and choice
  continue|warn|replan|halt. Verdict = max severity of the two;
  noul-p-only fallback (p>=0.7 halt, p>=0.5 warn); "unknown" when no
  backend answers — callers treat unknown as continue, a gate never
  kills on missing data. State sources: `normalize_state()` (caller
  dict), `state_from_taskdir()` (devin-dispatch taskdir: heartbeat =
  freshest artifact mtime, iterations = transcript steps/events rows,
  recent = run.*.log tail), CLI `--state/--taskdir/--health/--selftest`.
- **`scripts/board/runner-agent.py`** — `gate_pass()` added to the
  per-tick chain after `watchdog_pass`. For each active dispatch unit
  older than 45min and due per 15min interval, builds loop state
  (taskdir for dispatch, journal tail otherwise) and calls
  `lg.gate()`. WARN/REPLAN post a debounced card comment; HALT needs
  2 consecutive verdicts then `_signal_job(unit, TERM)` — the finish
  pass reports the run failed with "stagnation-gate HALT (noul p=…,
  choice=…, streak=N)" prepended to the result. Probe loaded via
  `lg_module()` (SourceFileLoader, repos.conf chaba checkout first).
  `RUNNER_STAGNATION_GATE=0` disables; no module/backend/error =
  no-op. Advisory by contract — never blocks claims.
- **`scripts/bench-edu-manage.py`** — opt-in `--stagnation-gate`:
  after each agent-lane task (from task 3, every `--gate-every`)
  `bench_loop_state()` feeds the trajectory to the gate;
  `--gate-strikes` (default 2) consecutive halts breaks the lane and
  records `agg["gate"]`. Default off — no behavior change otherwise.
- **`scripts/jev/loop-gate-replay.py`** (new) — replays recorded
  trajectories through `gate()` at every prefix + strikes simulation.
- **Tests** — `tests/test_loop_gate.py` (22) +
  `tests/board/test_runner_agent_gate.py` (11): verdict matrix,
  stub detection, degradation, strikes->SIGTERM, debounce, no-op
  paths. 33 new pass; 125 neighboring runner/bench tests still pass.
- **Docs/evidence** — `docs/ssot/jobs/bench/2026-11-24-jev-stagnation-gate.yml`;
  replay JSONs in `evals/results/jev/loop-gate-replay-20261124-{idc02,idc03}.json`.

## Spec deviation (measured, documented in code + job doc)

Card asked for "jev-student noul (proven) for the halt decision; real
Jev API for choice". Both halves failed measurement: arena v2 had
student stag=0.417 vs jevos=0.917, and the live replay shows student
returns p≈0.005–0.008 **flat on every trajectory** — stall, healthy,
agent-stall alike (same OOD collapse as code-decision's gates). Its
choice head is a detected stub (confidence=0, choice="answer") and is
skipped. Default backend order is therefore `jev-api → jevos →
jev-student` for both question types (`JEV_GATE_*_ORDER` env
override); student remains the only tailscale-reachable noul
fallback.

## Bench answer — does the gate HALT the 4.4h stall early?

**Yes, on jevos.** Replaying the real colibri rep-1 trajectory
(13 tasks × ~930s identical HTTP 429/TimeoutError, the actual
2026-10-24 stall shape) through `loop-gate-replay.py` on idc03:

- halt verdict from checkpoint k=3 (noul p 0.69–0.77, choice halt at
  every checkpoint); with the runner's 2-strike rule the lane stops
  at k=4 — **skips 9/13 tasks ≈ 2.3h of the 3.4h bench** (plus the
  ~1h prep/serve overhead the gate also avoids).
- healthy control (clawbot rep-1, 13/13 completed): continue at all
  11 checkpoints, noul p 0.21–0.26 — clean separation.
- agent-stall flavor (repeated identical tool=chat 429s): halt from
  k=3.
- Cost: 5.7–8.4s per gate call (one request, both questions) —
  negligible vs 930s/task.

**On student-only backends (idc02): the gate never fires** — p≈0.006
flat, verdict continue everywhere. Deployment therefore needs jevos
reachability (today: ad-hoc `./jev serve` on idc03 127.0.0.1:8017,
not a declared unit) or the real Jev API key (still blocked, KNB-0822).
Runner gate self-disables silently when no backend answers — noted as
a follow-up in the job doc.

## How to verify

```
python3 -m pytest tests/test_loop_gate.py tests/board/test_runner_agent_gate.py -x -q   # 33 pass
python3 scripts/jev/loop-gate.py --health
python3 scripts/jev/loop-gate.py --selftest | head
python3 scripts/jev/loop-gate-replay.py --traj stall --strikes 2   # on idc03 for jevos
```

lessons:
- jev-student's noul head collapses to p≈0.005 on out-of-distribution state shapes (this probe, code-decision gates) — "proven" arena numbers do not transfer across question formats; always replay on the real trajectory before trusting a backend for a new probe.
- jevos (idc03 127.0.0.1:8017) is the only working choice+noul backend but is an ad-hoc `./jev serve` process, not a declared unit — anything depending on it inherits an undeclared-service risk.
- runner-agent pass functions are unit-testable by module-load + attribute stubbing (m.api/m.unit_active/m._signal_job) — the established tests/board pattern; no subprocess needed.
- bench-edu-manage `--progress-log` JSONL was already a per-task heartbeat; the gate hook slots in after it with zero harness changes.
