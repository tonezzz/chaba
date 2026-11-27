# Dispatch outcome — fleet-restic-backup.service on tony-macbook (OPS-1486)

Card: `restic-backup-intermittent-exit-fix-unpinned` (unattended devin-dispatch, runner tony-dell).

## What was found

- `fleet-restic-backup.service` is a **user** oneshot on tony-macbook driving
  `~/.local/bin/fleet-restic-backup.sh` (13 lines, `set -euo pipefail`, no retry),
  logging to `~/var/log/fleet-restic.log`, repo
  `sftp:tony@tony-dell:/dell-backup/restic-fleet/tony-macbook`.
- Retained journal shows exactly two failures: **2026-11-23 06:46:11** and
  **2026-11-27 09:06:56** — both ~12–14s after a boot
  (`journalctl --list-boots`), i.e. `Persistent=true` catch-up runs before
  Tailscale/routes were up. Identical log line both times:
  `ssh: connect to host 100.68.142.13 port 22: Network is unreachable` →
  `Fatal: unable to open repository at sftp:tony@tony-dell:…`.
- **Not** a repo lock, **not** tony-dell down — the macbook's own uplink simply
  wasn't routed yet. All scheduled 05:15 runs succeeded in 1.8–4.9s.

## What changed

- `~/.local/bin/fleet-restic-backup.sh` on tony-macbook rewritten (backup of the
  old script kept at `fleet-restic-backup.sh.bak-20261127` and embedded in the
  job doc). Canonical copy committed at `scripts/ops/fleet-restic-backup.sh`.
- New behavior:
  - **Preflight**: parses `user@host` out of `RESTIC_REPOSITORY`, polls
    `ssh -o ConnectTimeout=5 -o BatchMode=yes <target> true` every 10s up to
    `FLEET_RESTIC_NET_WAIT=180s`; logs each wait; on exhaustion prints a
    `DIAGNOSIS:` line and exits 1 (real outage still alerts — nothing masked).
  - **Retry**: `run_restic` gives each restic invocation up to
    `FLEET_RESTIC_ATTEMPTS=4` tries, backoff `FLEET_RESTIC_BACKOFF=15s`
    doubling capped at 120s; output captured then classified by `diagnose()`
    into `DIAGNOSIS[step]` lines (network-unreachable / repo-lock / auth /
    unclassified). `forget --prune` still runs only after a successful backup.
  - Backup **not** disabled; unit untouched (`TimeoutStartUSec=infinity`
    verified, so retries can't be killed).
- `docs/ssot/jobs/infrastructure/2026-11-27-macbook-fleet-restic-retry.yml` —
  full job trail incl. rollback script.
- `docs/ssot/infrastructure/ssot.audit.hosts.yml` — macbook block now declares
  `fleet-restic-backup.{timer,service}` (was drift-invisible).

## Bugs caught during verification (fixed before live runs)

1. `$?` after `if cmd; then …; fi` **without else** is 0, not cmd's rc —
   rc is now captured inside the `else` branch.
2. First draft used `$1` as a log label **and** shifted it away, so restic
   received `restic /home/tony/.config/secrets …` → `unknown command`
   (4 wasted live attempts, ~106s, then fixed and redeployed).

## Verification

- Failure injection on `/tmp` copies: unreachable repo
  (`sftp:tony@192.0.2.1:22/x`, `NET_WAIT=12`) → 3 wait lines → `DIAGNOSIS:
  repo host … unreachable after 12s` → exit 1. `/bin/false` as restic →
  per-attempt `DIAGNOSIS`, `retrying in Ns`, `FATAL: backup failed rc=1`,
  forget skipped, exit 1.
- Live: 4 consecutive `systemctl --user start fleet-restic-backup.service`
  on tony-macbook at 09:53:09/26/32/37 — all `Result=success`,
  `ExecMainStatus=0`.
- Consumer proof on target: `restic -r /dell-backup/restic-fleet/tony-macbook
  snapshots` shows `65c3694b 2026-11-27 09:53:37 fleet-critical 387.413 MiB`;
  policy kept one snapshot/day 11-20→11-27.

## Commits (dispatch branch `dispatch/20261127-093800-fleet-restic-backup-service-on`)

- `904c15c1be5` fix(backup): fleet-restic-backup retry/backoff for post-boot
  network race (OPS-1486)
- `b047c0e36a4` chore(ssot): refresh dev-system assessment (pre-commit hook)

Card comms posted on `restic-backup-intermittent-exit-fix-unpinned` (done) and
`timer-alert-tony-macbook-fleet-restic-backup` (RESOLVED note — safe to close;
next scheduled run 2026-11-28 05:15).

## Follow-ups (not done — out of scope)

- idc02/idc03/tony-omen/mn01 still run the pre-retry 13-line script; same
  post-boot race applies. Fleet converge of `scripts/ops/fleet-restic-backup.sh`
  is a separate card candidate.

lessons:
- In bash, `$?` after `if cmd; then …; fi` with NO else branch is 0, not cmd's
  rc — capture rc inside an else or use `cmd && {…}`.
- fleet-restic-backup "intermittent exit 1" on macbook was never repo/lock —
  check `journalctl --list-boots` first: Persistent timers fire ~10s after
  boot, before Tailscale is up.
- When wrapping a CLI in a retry helper, keep the subcommand inside `"$@"` —
  using `$1` as a log label silently ate `restic backup` → "unknown command".
