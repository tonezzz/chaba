# kk-mac as a chaba dispatch runner (launchd port)

**Card:** `kk-mac-launchd-runner-port` (OPS-1019) — KK approved full
fleet use of kk-mac 2026-10-30.
**Host:** kk-mac — Mac16,9 Mac Studio, M4 Max 14-core, 36 GB unified
memory, macOS 15.x. Runner user: `kkkakk` (the login user, per the
card's scope — not the `adanest` service user).
**Provisioning:** `scripts/ops/kk-mac-runner-onboard.sh` (all steps
user-level, no sudo; the deploy-key enrolment at GitHub is the one
manual gate).
**Executor seam:** `scripts/board/runner-agent.py` —
`RUNNER_TASK_RUNTIME=auto|systemd|launchd`, `auto` → launchd on
darwin. Tests: `tests/board/test_runner_agent_launchd.py`.

## The systemd → launchd mapping

| Linux (systemd-run lane)                | macOS (launchd seam) |
|---|---|
| `systemd-run --user --unit=<u> --collect` | generated plist + wrapper under `~/.local/share/runner-agent/launchd/`, `launchctl bootstrap gui/<uid> <plist>` |
| `systemctl --user is-active`            | `launchctl print gui/<uid>/<u>` → `state = running` / `pid = N` |
| `RuntimeMaxSec=<t>`                     | wrapper watchdog: `set -m` + payload pgrp, TERM then KILL after 15 s at `t` |
| cgroup kill on unit death               | EXIT trap in the wrapper kills the payload pgrp (launchd kills only the job leader) |
| `Nice=`, `ionice`, `CPUQuota`, `MemoryMax`, `IOWeight` | plist `Nice`/`ProcessType=Background`/`LowPriorityIO` + `ulimit -v` in the wrapper — **no cgroup v2**; CPUQuota/MemoryMax/IOWeight have no equivalent and are documented no-ops |
| `journalctl --user -u`                  | `Standard{Out,Err}Path` → `~/.local/share/runner-agent/logs/<u>.log`; unified log available via `log show --predicate 'process == "runner-agent"'` |
| task-dir `exit_code` + `/run/user/.../runner-exit/<u>.code` | same task-dir `exit_code` + `~/.local/share/runner-agent/exit/<u>.code` (wrapper always writes it) |
| `systemctl kill --kill-whom=all`        | `kill -<sig> -<pgrp>` — the wrapper records the payload's pgrp leader in `launchd/<u>.pid` |
| `systemd-run --setenv`                  | plist `EnvironmentVariables` (defaults inject `HOME` + `PATH` incl. `/opt/homebrew/bin`) |
| `getloadavg(3)` overload gate           | `sysctl -n vm.loadavg` (5-min field ÷ cores) — `getloadavg` as fallback |
| unit record reaped by `--collect`       | job record reaped by `launchctl bootout` / reboot — the `.code` file is the durable verdict in both worlds |

Generated job plists deliberately live under `RUNNER_STATE/launchd/`,
**not** `~/Library/LaunchAgents` — agents there are scanned at login
and would re-run finished tasks. The runner's own 60-second poller is
the only LaunchAgent (`ai.chaba.runner-agent`).

Payloads are authored **once** in systemd ExecStart form — `$$` means a
literal `$` to the payload shell. The launchd seam strips that one
escape layer when writing the wrapper (`$$HOME` → `$HOME`). Never
hand-edit a payload to "macOS form" — both runtimes consume the same
text.

`collect()` keeps the identical evidence precedence on both runtimes:
task-dir `exit_code` (devin-task-\*) → `.code` file → registered-job
`last exit code` → **unproven → not ok** (an unproven exit never
reports success).

## What a launchd runner serves

- **Yes:** `executor=opencode` (+ the opencode lane route), `script`,
  `container` (if podman installed), `jules`, `nlm_batch`,
  `kk_mac_local`.
- **No:** `executor=devin` and unexecutored cards that don't resolve an
  opencode lane. `devin-dispatch.sh` drives `systemd-run` internally —
  outside this seam. Those cards stay queued for a Linux runner (the
  claimable gate declines with an explicit reason + comms note, and
  `start_task` double-guards so a forced claim can never invoke it).

## Provision (runs ON kk-mac as kkkakk)

```bash
git clone gh-chaba:tonezzz/chaba.git ~/CascadeProjects/chaba   # or scp the script
cd ~/CascadeProjects/chaba
bash scripts/ops/kk-mac-runner-onboard.sh            # all steps
```

Per-step: `preflight dirs deploykey checkout reposconf opencode
secrets agent verify`. The gates, in order:

1. **preflight** — Darwin/arm64, `hw.model=Mac16,9`, python3 ≥ 3.10
   (brew `python@3.12`; runner-agent uses 3.10-only syntax), git/CLT,
   `launchctl print gui/<uid>` reachable (i.e. kkkakk logged in —
   auto-login recommended for an unattended runner, or
   `LAUNCHD_DOMAIN=user`).
2. **deploykey** — generates `~/.ssh/id_chaba_deploy`, writes the
   fleet-standard `Host gh-chaba` alias + `url."gh-chaba:tonezzz/"
   .insteadOf` git rewrite, then **prints the pubkey for manual
   enrolment** (write deploy key on tonezzz/chaba). The step passes
   only when `git ls-remote gh-chaba:tonezzz/chaba.git` authenticates.
3. **checkout** — `~/CascadeProjects/chaba` exec checkout (role-stamped
   via `install-hooks.sh --role exec`).
4. **reposconf** — `~/.local/share/devin-dispatch/repos.conf` with the
   chaba row; runs the same `git push --dry-run` probe the runner's
   push guard will run. Declare `push:chaba` in `RUNNER_LABELS` only
   after the probe passes.
5. **opencode** — official installer → `~/.opencode/bin/opencode`
   (native darwin-arm64; `opencode_bin()` resolves it before PATH).
   Warns until `~/.config/secrets/litellm-keys.env` exists (lane
   payloads source `LITELLM_KEY_*` from it — same contract as Linux).
6. **agent** — installs `runner-agent.py` snapshot to
   `~/.local/bin/runner-agent`, writes + bootstraps
   `~/Library/LaunchAgents/ai.chaba.runner-agent.plist`
   (StartInterval=60, `RUNNER_HOST=kk-mac`, `RUNNER_TASK_RUNTIME=
   launchd`, `OPENCODE_LANES=1`, `RUNNER_LABELS=desktop,mac,arm64,cpu`
   — `desktop` arms the limits profile so tasks nice themselves out of
   KK's way; add `push:chaba` once the probe passes).

## Verify on the metal

```bash
launchctl print gui/$(id -u)/ai.chaba.runner-agent | head
tail -f ~/.local/share/runner-agent/runner-agent.log

# exercise the task seam end-to-end (writes plist+wrapper, bootstraps,
# collects the .code file):
python3 - <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location(
    "ra", "/Users/kkkakk/.local/bin/runner-agent")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print("runtime:", m.task_runtime())
print("launch err:", m.rt_launch("runner-selftest-1", "self test",
                                 "echo hi from launchd; sleep 2",
                                 timeout_s=30))
import time; time.sleep(4)
print("active:", m.unit_active("runner-selftest-1"))
print("collect:", m.collect("runner-selftest-1"))
PY
```

Expected: `launchd`, `""`, `False`, `(True, 'exit=0 …')`.

The X-presentation watchdog (`vsync_flood_hits`, `xrandr_probe`) is
Linux-only — on macOS its probes are inert and it never fires; the
SIGSTOP/SIGCONT path it would take does work (kill to the payload pgrp).

## Cap / limits policy for a shared family machine

- `RUNNER_CAP=1` default — raise only with Tony's sign-off.
- `desktop` in `RUNNER_LABELS` arms the limits profile: plist `Nice=10`
  + `LowPriorityIO` + `ulimit -v` (~75 % of `hw.memsize`) on every task
  job. `RUNNER_MAX_LOAD_PC=1.0` yields the queue when the machine is
  busy (5-min `vm.loadavg` per core).
- `pmset` sleep policy is owned by the Ada Nest onboarding
  (`kk-mac-onboard.sh power`) — don't double-manage it.

## Teardown

`CONFIRM_TEARDOWN=1 bash kk-mac-runner-onboard.sh teardown` — boots out
the poller + every registered `devin-task-*`/`runner-*` job and removes
the generated artifacts; keeps the checkout, deploy key, and opencode.
