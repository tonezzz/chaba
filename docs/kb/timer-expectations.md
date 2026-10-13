# Timer expectation sweep — detection over a single point of failure

Born 2026-10-13 from OPS-0531: `chaba-jobs.timer` was silently disabled
for ~2 days; 4 dispatcher jobs starved with zero signal. systemd does
not log *who* disables a user timer — prevention is impossible, so the
standard is **fast detection**.

## Model

- Per-job timers stay per-job (isolation, `Persistent` catchup,
  journald tags). Do NOT collapse to one mega-timer.
- `chaba-jobs.timer` is the single tick for `dispatch: dispatcher`
  interval jobs (`ssot.jobs.yml`); heavyweight/calendar jobs render
  their own `<id>.timer`.
- **Every live fleet timer must be declared** `expected_state: active`
  in `ssot.audit.hosts.yml` under the host's `expected_services`.
  Daily `audit-hosts.py` (drift-reconcile) then flags "expected timer
  disabled/missing" as a delta → card.

## Sweep procedure

1. Per host: `systemctl --user list-timers --all --no-legend` → timer
   basenames; filter OS noise (snap.*, ubuntu-insights, launchpadlib,
   fwupd, man-db, hash-named, logrotate, apt, dpkg, fstrim, motd).
2. Expected set = `ssot.jobs.yml` jobs for that host (id → `<id>.timer`,
   `dispatch: dispatcher` jobs covered by `chaba-jobs.timer`) + timers
   installed by other mechanisms (install scripts, manual) — all belong
   in audit.hosts regardless of which system renders them.
3. Diff both directions:
   - **declared-but-disabled/missing** → investigate (is the job
     migrated? retired? — check manifest host/enabled before enabling)
   - **live-but-undeclared** → add `{name: X.timer, type: timer,
     scope: user}` census line in that host's `expected_services`
4. New timers: whoever installs a timer adds the audit entry in the
   same commit — one line, no excuse.

## Hardening rule (job containers)

Dispatcher job commands that `podman run --name X` get a pre-clean
(`podman rm -f X`) in `job-dispatcher.py` — a timeout-killed client
leaves the name behind and `--rm` never fires; one crash used to brick
a recurring job forever.
