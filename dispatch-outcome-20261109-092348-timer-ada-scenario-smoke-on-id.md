# Dispatch outcome — timer-alert-idc03-ada-scenario-smoke (2026-11-09)

## Result
Root cause found and fixed in repo. This is a **new bug behind the old
alert**, not a re-fire of the 11-08 deploy-drift issue.

## What actually happened on idc03
- After yesterday's drift repair (units + wrapper refreshed, provider
  gate live, image rebuilt 10:34 +07), the alert mode changed from
  `result=exit-code` to `result=timeout`.
- Every hourly fire since 11-08 12:00 alternates:
  - quota-dead window → `ExecCondition` provider gate skips →
    `result=exec-condition` (not alertable, working as designed), or
  - healthy window → suite starts → `start operation timed out` at
    exactly :45 → SIGTERM → SIGKILL → `result=timeout` → sentinel
    re-fires `[still suspicious]`.
- Why it can never finish: `TimeoutStartSec=2700` (45min) vs a smoke
  tier that grew to **44 scenarios** at ~2.5min each (a fail reruns
  once) → a full pass needs ~90-120min. Observed pace: 26 scenarios per
  45min window (journal, 07:00 and 08:00 runs today).
- Latent second bug: the runner image (built 11-08 10:34 +07) predates
  the OPS-0581 entrypoint shim (`container-suite-run`, commit
  `1f3b48b22`, 11:02 +07), so even a completed run would exit 1 on
  findings → `exit-code` again. Same deploy vehicle fixes both.

## Changes (this worktree)
- `stacks/services/ada-scenario-runner/ada-scenario-smoke.container` —
  `TimeoutStartSec` 2700 → **7200** (+ rationale comment). Hourly timer
  kept: overlapping fires drop while a run is active, so effective
  cadence self-throttles to ~2h and recovers to hourly if the tier
  speeds up.
- `stacks/services/ada-scenario-runner/ada-scenario-full.container` —
  `TimeoutStartSec` 3600 → **43200**. Same latent bug: 203 scenarios ≈
  8.5h minimum vs a 1h cap; manual-only unit so it never alerted, but
  any authorized run would have been killed mid-suite.
- `stacks/services/ada-scenario-runner/install.sh` — schedule comment
  documents the effective ~2h smoke cadence.
- New trail doc:
  `docs/ssot/jobs/ada/2026-11-09-ada-scenario-smoke-timeoutstartsec.yml`
- Card comment posted via board-api with root cause + pending deploy.

## Still pending (needs a deploy — outside dispatch boundary)
- Re-run `stacks/services/ada-scenario-runner/install.sh` on idc03 from
  the synced exec checkout once this lands. One run installs the new
  timeouts AND rebuilds the image with the OPS-0581 shim — which is
  also the pending action on card `ada-scenario-quadlets-exit-contract`.
- Optional direction (carded in trail doc, not implemented): the smoke
  tier at 44 scenarios isn't a "smoke" anymore — if the hourly
  fast-signal intent matters, split a smoke-fast subset and demote the
  rest.

## How to verify (post-deploy)
```
ssh idc03 'md5sum ~/.config/containers/systemd/ada-scenario-smoke.container'   # == repo copy
ssh idc03 'systemctl --user show ada-scenario-smoke.service -p Result --value' # success after a pass
ssh idc03 'journalctl --user -u ada-scenario-smoke.service --since today | grep "scenarios:"'  # run reaches final marker
ssh idc03 'podman inspect localhost/ada-scenario-runner:latest --format "{{.Config.Entrypoint}}"'  # [/usr/local/bin/container-suite-run]
```
CMS `timer-timeline-idc03` should show the smoke row leaving
timeout/exit-code after the first full pass post-deploy.
