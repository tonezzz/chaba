# Dispatch outcome — tony-macbook-daytime-runner (2026-11-25)

Card: `tony-macbook-daytime-runner` (OPS-0059) — "tony-macbook as
daytime-elastic dispatch runner".

## What was found (verified live on tony-macbook)

- `runner-agent.timer` enabled+active (60s poll); installed
  `~/.local/bin/runner-agent` sha256 == repo `scripts/board/runner-agent.py`
  (no drift — the 19:06 ansible redeploy synced it). Live unit:
  `RUNNER_LABELS=macbook,local-8c,always-home RUNNER_CAP=4
  RUNNER_MAX_LOAD_PC=1.0` — fleet prose was stale at cap 3/gate 0.8; SSOT
  now mirrors live.
- The runner is already doing the job: journal shows it claimed this card
  plus two siblings at cap 4/4 (`devin-task-20261125-190949-...`,
  `deploy-ada-stagger-verify`, `ops-kkmac-agent-update-temps`). "Second
  runner slot" = live.
- Suspend exposure mapped: on AC, lid-close is ignored
  (`HandleLidSwitchExternalPower=ignore`) and GNOME idle-suspend on AC is
  `nothing` — the host already stays awake docked. On battery,
  `HandleLidSwitch=suspend-then-hibernate` (hibernate.conf overrides
  headless-crd.conf) → suspend → hibernate → **resume fails** → cold boot.
  Journal: failed hibernate-resume boots 11-21 07:14, 11-23 16:51+16:55,
  11-25 09:38. Filed as **SYS-1410**
  (`tony-macbook-hibernate-resume-broken-eve-8ac607`, backlog, high).

## What changed

Repo (this branch):
- `scripts/ops/macbook-day-awake.sh` — daemon holding
  `systemd-inhibit --what=sleep:idle --mode=block` while
  `daytime(07:00–23:00) AND (AC online OR (lid open AND battery>=30%))`.
  Night / battery+lid-closed / low-battery keep normal suspend — bag
  safety and offline_ok preserved (runner rejoins ≤60s after wake).
- `scripts/ops/macbook-day-awake.desktop` — XFCE autostart entry
  (respawn loop). Required because logind **block** inhibitors need a
  polkit session subject: `inhibit-block-sleep` is
  `allow_any=auth_admin_keep`, and user@1000.service / ssh /
  user-bus-activation callers are all session-less → denied (verified
  empirically; auth_admin is also ungrantable — no `admin` group on this
  host). Only a process inside a real logind session passes
  (`allow_active=yes`/`allow_inactive=yes`).
- `systemd/macbook-day-awake.service` — session-free variant, kept in
  repo for after the polkit rule lands (host copy removed — disabled-unit
  half-state, R2).
- `scripts/ops/lid-blank-watch.sh` + `systemd/lid-blank-watch.service` —
  versioned the previously host-local-only unit (declared in audit hosts,
  R1/R8 gap; content == live `~/.local/bin/lid-blank-watch`).
- SSOT: `ssot.kanban.yml` runner_fleet macbook → cap 4 gate 1.0 + day-awake
  note; `ssot.audit.hosts.yml` macbook block documents the autostart
  artifact; `ssot.mysystem.macbook.yml` runner/power sections refreshed.
- `docs/ssot/jobs/infrastructure/2026-11-25-macbook-daytime-runner.yml` —
  full trail.

Host (tony-macbook):
- `~/.local/bin/macbook-day-awake.sh` installed (0755).
- `~/.config/autostart/macbook-day-awake.desktop` installed — **engages at
  next XFCE/CRD login** (current session predates it).
- Nothing else running; the disabled user-service experiment was removed.

## Result / how to verify

- Condition logic verified with stubbed sysfs: daytime+AC=hold,
  night=release, battery+lid-closed=release, battery+lid-open+80%=hold.
- **Inhibitor not yet held** — it arms at next graphical login. Verify:
  `systemd-inhibit --list | grep 'daytime runner'` → expect a `block`
  entry on `sleep,idle` during 07:00–23:00 while on AC.
- Faster path: board request `day-awake-inhibit-deployed-via-xfce-auto-544ad5`
  asks Tony for one sudo polkit rule
  (`/etc/polkit-1/rules.d/50-macbook-day-awake.rules` granting tony
  inhibit-block-sleep+idle); then `systemctl --user enable --now
  macbook-day-awake.service` gives session-independent coverage.
- LAN-fast backup target: not implemented (optional per card; no consumer
  defined). `fleet-restic-backup.timer` already covers macbook→dell.

lessons:
- logind block inhibitors need a session subject — user services, ssh,
  and user-bus activation are all denied; XFCE autostart is the
  zero-privilege path, a polkit rule the session-free one.
- auth_admin_keep is ungrantable here (no `admin` group) — headless
  inhibit attempts just time out ~25s.
- tony-macbook hibernate-resume is broken → every battery suspend cycle
  cold-boots (SYS-1410); treat any suspend as fleet-offline.
- Fleet prose drift: live runner unit was cap 4/gate 1.0 vs documented
  cap 3/0.8 — mirror live, flag intent.
