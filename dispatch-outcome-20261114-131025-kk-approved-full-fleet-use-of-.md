# dispatch outcome — kk-mac-launchd-runner-port (OPS-1019)

Ported the dispatch task-unit seam in `scripts/board/runner-agent.py`
from Linux-only `systemd-run` to a runtime-detectable launchd
equivalent, and shipped the kkkakk provisioning path — code-complete
and fully mock-tested on Linux; on-metal verification is the remaining
gate before kk-mac joins `runner_fleet`.

## What changed

- `scripts/board/runner-agent.py` — `RUNNER_TASK_RUNTIME=auto|systemd|
  launchd` (auto→launchd on darwin) + `RUNNER_LAUNCHD_DOMAIN=gui|user`.
  One seam: `rt_launch()` starts every transient unit — all six former
  systemd-run call sites (container, script, kk_mac, staged profile,
  opencode, nlm ×2, jules) now route through it emitting the same
  ExecStart payload (`$$`→`$` de-escaped on the launchd side).
  `_launchd_launch` writes a plist + bash wrapper under
  `RUNNER_STATE/launchd/` and `launchctl bootstrap`s `gui/<uid>/`
  `<unit>`; the wrapper supplies what launchd lacks: pgrp watchdog for
  the wall-clock bound (TERM→KILL+15s), a recorded payload pgrp
  (`.pid` file) for renice/signals, an EXIT trap so a bootout drops
  the tree, and a durable `RUNNER_STATE/exit/<unit>.code` write.
  `collect()` keeps the identical evidence precedence (task-dir
  exit_code > .code > `last exit code` > unproven→not ok).
  `unit_active`/`units_for_card`/`unit_pids`/`enforce_task_limits`/
  watchdog throttles are runtime-branched; limits map to plist
  `Nice`/`ProcessType=Background`/`LowPriorityIO` + `ulimit -v` (no
  cgroup on macOS — CPUQuota/MemoryMax documented no-ops). Overload
  gate reads `sysctl -n vm.loadavg` on darwin; `hw.memsize` feeds
  `task_mem_max`. `claimable()` declines `executor=devin` and
  unexecutored cards with no opencode route on launchd (devin-dispatch
  drives systemd-run internally — the card waits for a Linux runner,
  reason + defer comms included); `start_task` double-guards.
- `tests/board/test_runner_agent_launchd.py` — 35 tests covering
  detect, plist/wrapper generation, bootstrap/bootout/refuse,
  active/collect precedence, pgrp pids+signals, units_for_card,
  sysctl parse + overload, claimable devin gate.
- `scripts/ops/kk-mac-runner-onboard.sh` — idempotent kkkakk
  provisioning: preflight (arm64/Mac16,9/py≥3.10/gui domain),
  `id_chaba_deploy` + `Host gh-chaba` alias + `insteadOf` rewrite
  (GitHub enrolment is the one manual gate), exec checkout,
  repos.conf + push probe, opencode darwin-arm64 install, secrets
  check, `ai.chaba.runner-agent` LaunchAgent (60s poll, CAP=1,
  labels `desktop,mac,arm64,cpu`, OPENCODE_LANES=1), verify, teardown.
- `docs/kb/kk-mac-launchd-runner.md` — systemd→launchd mapping table,
  per-step gates, on-metal verify recipe, cap policy, teardown.
- `docs/ssot/jobs/kanban/2026-11-14-kk-mac-launchd-runner-port.yml` —
  durable job record incl. gaps.
- `docs/ssot/kanban/ssot.kanban.yml` — `runner_fleet` notes kk-mac as
  STAGED.

## Result / verification

- `python3 -m py_compile` — OK. `bash -n` on the provisioning script —
  OK. YAML parses.
- `python3 -m unittest discover -s tests/board` — **580 tests, all
  OK** (35 new). Linux systemd path unchanged: `rt_launch`'s systemd
  arm composes the historical argv verbatim.
- Not run on the metal: provisioning (`kk-mac-runner-onboard.sh`),
  real `launchctl bootstrap/print`, and a live claim remain to verify
  on kk-mac — the job yml's `gaps_remaining` lists the ordered steps
  (deploy-key enrolment, kkkakk login session or `LAUNCHD_DOMAIN=user`,
  litellm keys, then `push:chaba` + fleet labels).

## Notes for reviewers

- `executor=devin` and unexecutored non-opencode cards stay
  Linux-runner-only by design — porting `devin-dispatch.sh` itself is
  separate work if ever needed.
- Pre-existing (not introduced here): `start_nlm_lane`/`finish_nlm_lane`
  and the nlm_batch route are defined twice in runner-agent.py —
  byte-identical upstream merge duplication, second def wins; noted in
  the job yml.
- Board updated via board-api comments; card files untouched.
