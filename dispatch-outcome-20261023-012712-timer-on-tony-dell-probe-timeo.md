# Dispatch outcome — podman-lock-wedge-watchdog (OPS-0726)

## What was built

Card `podman-lock-wedge-watchdog` — the self-heal half of the 2026-10-16
tony-dell collapse (runbook
`docs/ssot/jobs/infrastructure/2026-10-16-tony-dell-podman-lock-wedge.yml`).
Commit `01f36e43` on branch `dispatch/20261023-012712-timer-on-tony-dell-probe-timeo`:

- `scripts/ops/podman-lock-watchdog.py` — the watchdog. Per tick:
  `timeout 8 podman ps`; on 3 consecutive failures AND zero live
  podman/docker CLI processes (conmon/pause/catatonit/fuse-overlayfs
  excluded — they don't hold the CLI locks) it removes
  `/dev/shm/libpod_rootless_lock_<uid>*`, dead `pause.pid` under
  `/run/user/<uid>/containers/**` (live pause pids kept; recycled pids
  count as stale), and `alive.lck`; runs `timeout 20 podman system
  renumber` (`PODMAN_WD_RENUMBER=0` skips); re-probes `timeout 10
  podman ps`. Alerts via chaba-admin event (HA chaba-event-log.py,
  local + ssh fallback) AND LINE via ada-line-relay `:8912/send`
  (loopback + `ssh idc03` fallback) on both auto-recovery (warn) and
  failure-to-recover (critical). One alert per episode, 6h resend cap,
  20min re-attempt cooldown, one JSON line per tick to journald.
  `--dry-run` (real probe, no deletes/alerts) and `--self-test`.
- `docs/ssot/infrastructure/ssot.jobs.yml` — job `podman-lock-watchdog`,
  host `tony_dell`, `dispatch: systemd`, `every: 2min`, `timeout: 2m`,
  exec from the exec checkout `%h/CascadeProjects/chaba`.
- `systemd/generated/tony_dell/podman-lock-watchdog.{service,timer}` —
  rendered via `render-jobs.py` (CI drift-check requires them committed).
- `tests/ops/test_podman_lock_watchdog.py` — 7 offline unittest cases.
- `docs/ssot/jobs/infrastructure/2026-10-23-podman-lock-watchdog.yml` —
  job doc (install + verify + edge semantics).

## Verified

- `unittest`: 7/7 pass (threshold, live-CLI deferral, recovery alert
  dedup, cooldown suppression, external-recovery reset, live/dead
  pause.pid handling).
- `--self-test`: 8/8 PASS.
- Live `--dry-run` with injected failing probe + fake stale files:
  signature fired at tick 3, all 3 artifacts listed for removal,
  critical alert path taken.
- `render-jobs.py --check`: manifest valid (73 jobs); re-render
  idempotent (no drift). Pre-commit SSOT validation passed.

## NOT done (gated)

- **No install/deploy on tony-dell** — dispatch rules forbid it and this
  runner can't reach the host's systemd. Install step (documented in the
  job doc): on tony-dell exec checkout —
  `git pull && python3 scripts/render-jobs.py --host tony_dell --install`.
- Card remains `backlog`; column left for Tony/board convention (field
  ownership). Progress posted via board-api comment.

## How to verify on tony-dell after install

```
python3 scripts/ops/podman-lock-watchdog.py --dry-run
systemctl --user list-timers podman-lock-watchdog.timer
journalctl --user -u podman-lock-watchdog.service -f   # one JSON line/2min
```
