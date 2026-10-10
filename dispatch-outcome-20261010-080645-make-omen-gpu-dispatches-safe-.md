# dispatch-outcome-20261010-080645-make-omen-gpu-dispatches-safe-

Card: `omen-gpu-display-wedge` — make omen GPU dispatches safe on an
interactive host. Seam: `scripts/board/runner-agent.py` (deploys
single-file to `~/.local/bin/runner-agent`).

## What changed

**scripts/board/runner-agent.py**

1. **Task unit resource limits** (armed when `desktop` is in
   `RUNNER_LABELS` — tony-omen carries it — or `RUNNER_TASK_LIMITS=1`):
   `Nice=10`, `IOSchedulingClass=best-effort/6` (ionice),
   `CPUQuota=75%-of-CPUs`, `CPUWeight=50`, `MemoryMax=75%-of-RAM`,
   `IOWeight=50`.
   - container/script types: `--property=` args spliced into the
     existing systemd-run argv in `start_task`.
   - dispatch type: `DISPATCH_UNIT_PROPS` exported to `devin-dispatch
     start` (it splices it into its own systemd-run) AND
     `enforce_task_limits()` post-start — `systemctl --user set-property`
     for the cgroup props + renice/ionice of the unit's `cgroup.procs`
     (Nice/ionice aren't cgroup props; children inherit). This covers
     hosts whose devin-dispatch predates `DISPATCH_UNIT_PROPS`.

2. **VRAM pre-flight** (`gpu_preflight`, runs BEFORE the claim POST so a
   deferred card stays queued): gpu-labeled cards need
   `max(action.gpu.min_free_mb, RUNNER_GPU_MIN_FREE_MB=512)` MB free in
   `nvidia-smi`. Shortfall → defer + debounced comms note
   (`~/.local/share/runner-agent/gpu-defer.json`, 6h/reason). Need >
   total → refused with a "fix the spec" comms note. No nvidia-smi → gpu
   cards not claimed. Side benefit: serializes GPU work — once one task
   eats VRAM the next gpu card defers (ssot.gpu one-workload policy).

3. **Presentation watchdog** (`watchdog_pass`, each agent pass while a
   gpu task is active; `RUNNER_GPU_WATCHDOG`, auto = `desktop` label):
   stall = ≥150 `GetVSyncParametersIfAvailable` hits in the last ~2min of
   journal + Xorg log tails, OR `xrandr --verbose` timing out/failing on
   a live X socket (auth failures skipped — not a wedge). Strike 1:
   CPUQuota=30% + renice 19. Strike ≥2: `SIGSTOP --kill-whom=all` + comms
   carrying the unstick runbook. ~10min paused: one reminder. 2 healthy
   probes: `SIGCONT` + limits re-applied. State in `state.json` `wd`
   dict.

4. **Unstick documentation**: card comms (posted live via board-api) +
   runbook `docs/ssot/jobs/kanban/2026-10-10-omen-gpu-dispatch-safety.yml`
   — `cat /sys/class/tty/tty0/active` / `loginctl` to find the session VT,
   `sudo chvt 3; sleep 2; sudo chvt <vt>`, resume via SIGCONT or auto.

**tests/board/test_runner_agent_gpu.py** — 19 tests: prop argv,
DISPATCH_UNIT_PROPS env, preflight defer/refuse/pass/no-smi, watchdog
strike→pause→resume. `python3 -m unittest tests.board.test_runner_agent_gpu`.

**docs/ssot/kanban/ssot.kanban.yml** — card_schema gains `action.gpu`
(`{min_free_mb}`, bare int / `min_vram_mb` aliases); `runner_hosts`
documents the guards + env knobs.

## Result

Committed as d7e904e2 on `dispatch/20261010-080645-...`. 19/19 new tests
pass; full `tests/board` suite 72 tests OK. ssot YAML validates
(python-yaml; node/ssot-validate-all.mjs unavailable on this host).

## Not done / follow-ups

- **Not deployed** (rails: no deploy without approval). Deploy:
  `scp scripts/board/runner-agent.py tony-omen:~/.local/bin/runner-agent`
  + chmod +x; confirm tony-omen's devin-dispatch has DISPATCH_UNIT_PROPS
  (post-start set-property covers the gap regardless).
- GPU cards that bench big models should declare `action.gpu.min_free_mb`
  honestly — without it only the 512MB floor applies.
- kanban-dispatch (tony-dell local path) untouched by design — same
  effect available via `Environment=DISPATCH_UNIT_PROPS=...` on its
  service.

## How to verify

- After redeploy on tony-omen, queue a gpu card and check
  `systemctl --user show devin-task-<id> -p CPUQuota -p MemoryMax -p Nice`.
- Fill VRAM (or lower `RUNNER_GPU_MIN_FREE_MB`) → the card defers and a
  `gpu preflight: ... deferred` comms note appears.
- Watchdog drill: `RUNNER_VSYNC_FLOOD_MIN=1` + logger-spam the signature,
  or watch a real gpu dispatch during load; unit should deprioritize then
  freeze (`systemctl --user status` shows tasks stopped) with comms
  notes on the card.

lessons:
  - A healthy X server is not a healthy display — x11grab kept capturing
    the stale frame through the wedge; detect the signature flood / hung
    xrandr, not daemon liveness.
  - dispatch-type units are created inside devin-dispatch, a process away
    from runner-agent — post-start `set-property` + renice of
    cgroup.procs is the version-proof enforcement path (DISPATCH_UNIT_PROPS
    already existed for the fast path).
  - `systemctl kill` needs `--kill-whom=all` to SIGSTOP a whole process
    tree; Nice/ionice aren't cgroup props — renice the pids.
  - xrandr auth fast-failures must not count as a wedge — only timeouts
    or non-auth errors; missing XAUTHORITY would otherwise pause every
    gpu task.
  - chvt modeset reset needs root — a user-service watchdog can only
    pause the offender and put the reset steps in comms.
