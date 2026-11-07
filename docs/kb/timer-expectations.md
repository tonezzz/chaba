# Timer expectation sweep — detection over a single point of failure

Born 2026-10-13 from OPS-0531: `chaba-jobs.timer` was silently disabled
for ~2 days; 4 dispatcher jobs starved with zero signal. systemd does
not log *who* disables a user timer — prevention is impossible, so the
standard is **fast detection**.

## Model

- Per-job timers stay per-job (isolation, `Persistent` catchup,
  journald tags). Do NOT collapse to one mega-timer.
- `chaba-jobs.timer` is the legacy single tick for `dispatch: dispatcher`
  interval jobs (`ssot.jobs.yml`). After the 2026-10-29 OPS-0790
  migration no dispatcher jobs remain — every job renders its own
  `<id>.timer`; the tick retires once replacement timers are verified.
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

Job commands that `podman run --name X` get a best-effort pre-clean
(`ExecStartPre=-/usr/bin/podman rm -f X`) emitted by `render-jobs.py` —
a timeout-killed client leaves the name behind and `--rm` never fires;
one crash used to brick a recurring job forever. (Before the OPS-0790
migration the same guard lived as a subprocess preclean in
`job-dispatcher.py`.)

## Exit-code contract (OPS-0581, decided 2026-10-13)

A timer job's exit code means exactly one thing: **did the run
complete?**

- **exit 0** — the job ran to completion, regardless of what it found.
  Findings (audit failures, breaches, missed canaries, new network
  devices, scenario failures) travel on their own channels: report
  files, `docs/ssot/focus-inbox/`, ops-event docs, CMS pages, kanban
  cards.
- **non-zero** — the job did NOT complete: unhandled crash, timeout,
  missing dependency, lock contention that prevented the run, usage
  error. Only this alerts the timer-sentinel (red `timer-alert-*` card).

Rejected alternative (kind: finding-reporter in ssot.audit.hosts.yml +
sentinel reclassifies exit-1 as yellow "see report"): keeps two
meanings on one code, every new consumer must learn the kind map, and
a `failed` unit still looks identical to a crash in systemctl /
journald. Exit 0 = success is the contract every tool already
understands.

Rules:

- Finding-reporters MUST have a durable findings channel *before*
  switching to exit 0 — check the report file / focus-inbox writer /
  ops-event emit exists, don't just flip the code.
- Wrappers MAY translate a child tool's legacy "exit 1 = findings"
  into the contract, but only when they can prove the run completed
  (e.g. `scenario-suite-run.sh` greps the benchmark's final-report
  `**Score:` marker — exit 1 without it stays nonzero as a real crash).
- `known_failed` entries for converted jobs are retained one cycle as
  rollout cover; a fresh failure after conversion is a real crash.

Converted 2026-10-13 (were red-alerting the sentinel on findings):
`arp-inventory-scan` (tony-omen), `chaba-audit-watchdog` (tony-omen),
`chaba-audit` + `chaba-audit-full` (`run.mjs`, idc02/tony-dell),
`mddb-memory-standard` (idc03), `ada-recall-canary` (idc03),
`ada-scenario-{research,cms,memory,reports,tools,casting}` (idc03, via
`scenario-suite-run.sh` — needs `install.sh` re-run or the wrapper
copied to `~/.local/share/ada-scenario-runner/` on idc03 to deploy).

Residual finding-reporters still on exit-nonzero-on-findings (migrate
when next touched, or fix on the ada-voice side): `ada-memory-sync`,
`mddb-vector-reindex`, `ada-scenario-smoke` + `ada-scenario-full`
(quadlets — bypass the wrapper).
